# Copyright (c) 2026 Simon Ugorji
# SPDX-License-Identifier: Apache-2.0

"""Which CDP browser and tab each chat is driving, for the live view.

Several chats can run at once against different Chromium instances (the pool
hands each project a port) or against different tabs of one instance. The live
view has to follow the chat the user opened it from, so the toolkit records the
browser it resolved here and the stream looks it up instead of guessing 9222.
"""

from __future__ import annotations

import threading
import time
from typing import Any

# Entries outlive a completed turn (the tab stays open), so keep them for a
# working session and let older ones fall out instead of growing forever.
_TTL_SECONDS = 12 * 60 * 60

_lock = threading.Lock()
_by_chat: dict[tuple[str, str | None], dict[str, Any]] = {}


def _chat_key(
    project_id: str | None, task_id: str | None
) -> tuple[str, str | None]:
    return (str(project_id or ""), str(task_id) if task_id else None)


def _prune(now: float) -> None:
    stale = [
        key
        for key, entry in _by_chat.items()
        if now - float(entry.get("updated_at", 0)) > _TTL_SECONDS
    ]
    for key in stale:
        _by_chat.pop(key, None)


def remember_browser(
    project_id: str | None,
    *,
    task_id: str | None = None,
    port: int | None = None,
    session_id: str | None = None,
    target_id: str | None = None,
    url: str | None = None,
) -> None:
    """Record (or refresh) the browser a chat is using.

    Only the fields passed are overwritten, so callers can update the tab
    without re-sending the port. `session_id` is the toolkit session whose
    ``about:blank#eigent-<session>`` sentinel marks that chat's first tab.
    """
    if not project_id:
        return
    now = time.time()
    with _lock:
        _prune(now)
        entry = _by_chat.setdefault(
            _chat_key(project_id, task_id), {"updated_at": now}
        )
        if port is not None:
            entry["port"] = int(port)
        if session_id is not None:
            entry["session_id"] = session_id
        if target_id is not None:
            entry["target_id"] = target_id
        if url is not None:
            entry["url"] = url
        entry["updated_at"] = now


def lookup_browser(
    project_id: str | None, task_id: str | None = None
) -> dict[str, Any] | None:
    """Return the browser for this chat, falling back to its project's latest."""
    if not project_id:
        return None
    now = time.time()
    with _lock:
        _prune(now)
        key = _chat_key(project_id, task_id)
        exact = _by_chat.get(key)
        if exact and exact.get("port") is not None:
            return dict(exact)
        latest: dict[str, Any] | None = None
        for (pid, _tid), entry in _by_chat.items():
            if pid != str(project_id) or entry.get("port") is None:
                continue
            if latest is None or entry.get("updated_at", 0) > latest.get(
                "updated_at", 0
            ):
                latest = entry
        if latest is not None:
            return {**latest, **(exact or {})}
        return dict(exact) if exact else None


def forget_browser(project_id: str | None, task_id: str | None = None) -> None:
    if not project_id:
        return
    with _lock:
        _by_chat.pop(_chat_key(project_id, task_id), None)


def clear() -> None:
    """Drop every entry (tests, and a brain-side reset)."""
    with _lock:
        _by_chat.clear()
