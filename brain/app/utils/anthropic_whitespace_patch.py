# Copyright (c) 2026 Simon Ugorji

"""Startup patch: strip trailing whitespace from assistant messages sent to
Anthropic.

Anthropic rejects a request whose FINAL message is an assistant message whose
text ends with whitespace ("final assistant content cannot end with trailing
whitespace"). This surfaces on multi-step / extended-thinking turns where the
model's own assistant text (which may end with a newline) is fed back into the
next request. CAMEL's `AnthropicModel` builds the request messages but does not
sanitize this, so we wrap its OpenAI->Anthropic converter to rstrip assistant
text blocks. Idempotent and defensive: any failure leaves CAMEL untouched.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("anthropic_whitespace_patch")


def _rstrip_message_content(msg: dict) -> None:
    """rstrip trailing whitespace on an assistant message's text in place."""
    content = msg.get("content")
    if isinstance(content, str):
        msg["content"] = content.rstrip()
        return
    if isinstance(content, list):
        # Block list: rstrip the LAST text block (that's what ends the message).
        for block in reversed(content):
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    block["text"] = text.rstrip()
                break


def apply() -> None:
    try:
        from camel.models.anthropic_model import AnthropicModel
    except Exception:  # pragma: no cover - camel layout changed
        logger.debug("AnthropicModel not importable; whitespace patch skipped")
        return

    orig = getattr(
        AnthropicModel, "_convert_openai_to_anthropic_messages", None
    )
    if orig is None or getattr(orig, "_undisclosed_ws_patched", False):
        return

    def wrapped(self, messages):
        system_message, anthropic_messages = orig(self, messages)
        try:
            # rstrip every assistant message's text — harmless for interior
            # ones, required for the final one. Anthropic only forbids trailing
            # whitespace on assistant turns (user/tool content is fine).
            for m in anthropic_messages or []:
                if isinstance(m, dict) and m.get("role") == "assistant":
                    _rstrip_message_content(m)
        except Exception:  # pragma: no cover - never break the request path
            logger.debug("assistant whitespace rstrip failed", exc_info=True)
        return system_message, anthropic_messages

    wrapped._undisclosed_ws_patched = True
    AnthropicModel._convert_openai_to_anthropic_messages = wrapped
    logger.info(
        "Patched AnthropicModel to strip trailing whitespace from assistant "
        "messages"
    )
