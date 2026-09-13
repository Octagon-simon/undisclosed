# Copyright (c) 2026 Simon Ugorji

"""Startup patch: sanitize assistant messages sent to Anthropic.

Anthropic rejects two things on assistant turns that CAMEL's `AnthropicModel`
does not guard against when it feeds the model's own prior output back into the
next request (multi-step / extended-thinking turns):

1. **Trailing whitespace on the FINAL assistant message** — "final assistant
   content cannot end with trailing whitespace". The model's text often ends in
   a newline.
2. **Empty / whitespace-only text content blocks on a NON-final assistant
   message** — "text content blocks must be non-empty" / "all messages must
   have non-empty content except the optional final assistant message". This
   shows up with models that emit a thinking-only turn (e.g. sonnet-5 returns a
   thinking block plus an empty visible-text block): once another message
   follows it, that empty text block is illegal.

We wrap CAMEL's OpenAI->Anthropic converter to (a) rstrip assistant text and
(b) drop empty text blocks, while preserving a legitimately-empty FINAL
assistant turn (Anthropic allows that — it's the prefill slot). Non-text blocks
(tool_use, thinking, …) are never touched, so tool/thinking continuation is
unaffected. Idempotent and defensive: any failure leaves CAMEL untouched.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("anthropic_whitespace_patch")


def _sanitize_assistant(msg: dict, *, is_final: bool) -> bool:
    """Sanitize one assistant message in place.

    Returns True to keep the message, False to drop it (only ever drops a
    message that would otherwise be sent with NO content at all, which Anthropic
    rejects — and only when it is not the final turn, where empty is allowed).
    """
    content = msg.get("content")

    if isinstance(content, str):
        stripped = content.rstrip()
        msg["content"] = stripped
        # Empty string content is allowed only as the final assistant turn.
        return bool(stripped) or is_final

    if isinstance(content, list):
        # rstrip the LAST text block (that's what ends the message), then drop
        # every empty/whitespace-only text block so none is sent as illegal
        # empty content. tool_use / thinking / other blocks are preserved.
        for block in reversed(content):
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    block["text"] = text.rstrip()
                break
        kept_blocks = [
            b
            for b in content
            if not (
                isinstance(b, dict)
                and b.get("type") == "text"
                and not str(b.get("text") or "").strip()
            )
        ]
        # Mutate in place so any external reference to the list stays valid.
        content[:] = kept_blocks
        # A fully-empty block list is allowed only as the final assistant turn;
        # anywhere else it must be dropped (an empty interior assistant message
        # is degenerate and should not occur, but Anthropic hard-rejects it).
        return bool(kept_blocks) or is_final

    # Unknown content shape — leave it alone.
    return True


def _sanitize_message_list(messages: object) -> object:
    """Sanitize every assistant message in a full request `messages` list.
    Drops an empty INTERIOR assistant message (illegal), keeps an empty FINAL
    one (allowed prefill). Mutates dict items in place; returns the (possibly
    filtered) list. Non-list input is returned unchanged."""
    if not isinstance(messages, list):
        return messages
    last_idx = len(messages) - 1
    kept = []
    for i, m in enumerate(messages):
        if isinstance(m, dict) and m.get("role") == "assistant":
            if _sanitize_assistant(m, is_final=(i == last_idx)):
                kept.append(m)
            # else: drop the empty interior assistant message
        else:
            kept.append(m)
    return kept


def _patch_anthropic_sdk() -> None:
    """Sanitize assistant messages at the Anthropic SDK boundary — the LAST
    point before the request leaves, covering every path (streaming via
    create(stream=True), non-streaming, prefills, cache_control wrapping, and
    any CAMEL version) regardless of how the messages list was built. This is
    the belt to the converter patch's suspenders: the converter patch can miss
    if CAMEL renames its method or appends a message after conversion; this
    can't."""
    try:
        import anthropic.resources.messages.messages as _am
    except Exception:  # pragma: no cover - anthropic layout changed
        logger.debug("anthropic Messages module not importable; SDK patch skipped")
        return

    patched_any = False
    for cls_name in ("Messages", "AsyncMessages"):
        cls = getattr(_am, cls_name, None)
        if cls is None:
            continue
        orig_create = getattr(cls, "create", None)
        if orig_create is None or getattr(
            orig_create, "_undisclosed_ws_patched", False
        ):
            continue

        def _make(orig):
            # Plain def works for BOTH sync and async: we only mutate kwargs
            # synchronously before delegating; the async `create` returns an
            # awaitable that the caller awaits unchanged.
            def create(self, *args, **kwargs):
                msgs = kwargs.get("messages")
                if msgs is not None:
                    try:
                        kwargs["messages"] = _sanitize_message_list(msgs)
                    except Exception:  # pragma: no cover - never break sends
                        logger.debug(
                            "SDK-boundary messages sanitize failed",
                            exc_info=True,
                        )
                return orig(self, *args, **kwargs)

            create._undisclosed_ws_patched = True
            return create

        setattr(cls, "create", _make(orig_create))
        patched_any = True

    if patched_any:
        logger.info(
            "Patched Anthropic SDK Messages.create (sync+async) to sanitize "
            "assistant messages at the request boundary"
        )


def apply() -> None:
    # ALWAYS patch the SDK boundary first — it's the bulletproof layer and does
    # not depend on CAMEL's internals being where we expect.
    _patch_anthropic_sdk()

    try:
        from camel.models.anthropic_model import AnthropicModel
    except Exception:  # pragma: no cover - camel layout changed
        logger.debug("AnthropicModel not importable; converter patch skipped")
        return

    orig = getattr(
        AnthropicModel, "_convert_openai_to_anthropic_messages", None
    )
    if orig is None or getattr(orig, "_undisclosed_ws_patched", False):
        return

    def wrapped(self, messages):
        system_message, anthropic_messages = orig(self, messages)
        try:
            msgs = anthropic_messages or []
            last_idx = len(msgs) - 1
            kept = []
            for i, m in enumerate(msgs):
                if isinstance(m, dict) and m.get("role") == "assistant":
                    if _sanitize_assistant(m, is_final=(i == last_idx)):
                        kept.append(m)
                    # else: drop the empty interior assistant message
                else:
                    kept.append(m)
            # Only rebuild the list if we actually dropped a message, and mutate
            # in place so the caller's returned reference keeps pointing at it.
            if isinstance(anthropic_messages, list) and len(kept) != len(msgs):
                anthropic_messages[:] = kept
        except Exception:  # pragma: no cover - never break the request path
            logger.debug("assistant message sanitize failed", exc_info=True)
        return system_message, anthropic_messages

    wrapped._undisclosed_ws_patched = True
    AnthropicModel._convert_openai_to_anthropic_messages = wrapped
    logger.info(
        "Patched AnthropicModel to sanitize assistant messages (rstrip "
        "trailing whitespace + drop empty text blocks)"
    )
