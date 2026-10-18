# Copyright (c) 2026 Simon Ugorji

"""Repair tool-call pairing before a model request.

An interrupted turn (user Stop, cancellation, brain restart) can leave an
assistant message carrying `tool_calls` in memory without the matching `tool`
replies. Every later request then fails with:

    An assistant message with 'tool_calls' must be followed by tool messages
    responding to each 'tool_call_id'.

The turn never completes, so the session looks frozen and repeats the same 400
until it is cleared. Repairing the payload at the request boundary lets the
next turn proceed: unanswered tool calls are dropped (the assistant's text is
kept) and tool messages with no surviving call are discarded.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("tool_call_repair")


def _call_id(call: Any) -> str | None:
    """Identifier of a tool call, from a dict or an SDK object."""
    if isinstance(call, dict):
        value = call.get("id")
    else:
        value = getattr(call, "id", None)
    return value if isinstance(value, str) else None


def _reply_id(message: dict) -> str | None:
    value = message.get("tool_call_id")
    return value if isinstance(value, str) else None


def _is_empty(message: dict) -> bool:
    """True when a message carries no text and no non-text parts."""
    content = message.get("content")
    if content is None:
        return True
    if isinstance(content, str):
        return not content.strip()
    if isinstance(content, list):
        for part in content:
            if isinstance(part, str):
                if part.strip():
                    return False
            elif isinstance(part, dict):
                if part.get("type") != "text":
                    return False
                if str(part.get("text") or "").strip():
                    return False
        return True
    return False


def repair_tool_call_pairing(messages: Any) -> int:
    """Drop unpaired tool calls and replies from `messages`, in place.

    Returns the number of messages removed. Safe on any input shape: a
    non-list is left untouched.
    """
    if not isinstance(messages, list) or not messages:
        return 0

    repaired: list[dict] = []
    removed = 0
    index = 0
    total = len(messages)

    while index < total:
        message = messages[index]
        if not isinstance(message, dict):
            repaired.append(message)
            index += 1
            continue

        role = message.get("role")
        if role == "assistant" and message.get("tool_calls"):
            replies: list[dict] = []
            cursor = index + 1
            while (
                cursor < total
                and isinstance(messages[cursor], dict)
                and messages[cursor].get("role") == "tool"
            ):
                replies.append(messages[cursor])
                cursor += 1

            requested = message["tool_calls"]
            answered = {_reply_id(reply) for reply in replies}
            calls = [call for call in requested if _call_id(call) in answered]
            kept_ids = {_call_id(call) for call in calls}

            kept_replies: list[dict] = []
            seen: set[str | None] = set()
            for reply in replies:
                reply_id = _reply_id(reply)
                if reply_id not in kept_ids or reply_id in seen:
                    removed += 1
                    continue
                seen.add(reply_id)
                kept_replies.append(reply)

            if calls:
                removed += len(requested) - len(calls)
                if len(calls) == len(requested):
                    repaired.append(message)
                else:
                    repaired.append({**message, "tool_calls": calls})
                repaired.extend(kept_replies)
            elif not _is_empty(message):
                repaired.append(
                    {k: v for k, v in message.items() if k != "tool_calls"}
                )
                removed += len(requested)
            else:
                removed += 1 + len(requested)

            index = cursor
            continue

        if role == "tool":
            # A reply with no preceding call is rejected just as hard.
            removed += 1
            index += 1
            continue

        repaired.append(message)
        index += 1

    if removed:
        messages[:] = repaired
        logger.warning(
            "Repaired %d unpaired tool-call message(s) before the model "
            "request; an interrupted turn left the history inconsistent.",
            removed,
        )
    return removed
