# Copyright (c) 2026 Simon Ugorji

"""Lightweight debug-dump helper.

Enable with UNDISCLOSED_DEBUG=1 to dump the useful-for-debugging bits of a turn
— the prompt/messages sent to the model, tool calls + their args/results, the
model response (content + reasoning), token usage, and per-chunk streaming
structure. Dumps go to the brain log (prefixed `[DEBUG:<category>]`) AND to a
per-task file under ~/.undisclosed/debug/<task>.log for easy sharing.

Everything is a no-op when the flag is off, and every dump is best-effort — a
debug hook must never break the request path.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from app.component.environment import env

logger = logging.getLogger("undisclosed.debug")

# Truncate any single dumped value to keep the log readable / files bounded.
_MAX_LEN = 12000


def debug_enabled() -> bool:
    return (env("UNDISCLOSED_DEBUG", "0") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _debug_dir() -> str:
    root = env("UNDISCLOSED_DEBUG_DIR", "") or os.path.expanduser(
        "~/.undisclosed/debug"
    )
    os.makedirs(root, exist_ok=True)
    return root


def debug_dump(category: str, data: Any, *, task_id: str = "") -> None:
    """Record a debug entry. No-op unless UNDISCLOSED_DEBUG is on."""
    if not debug_enabled():
        return
    try:
        if not isinstance(data, str):
            data = json.dumps(data, default=str, ensure_ascii=False)
        if len(data) > _MAX_LEN:
            data = data[:_MAX_LEN] + f"…(+{len(data) - _MAX_LEN} chars)"
        suffix = f" task={task_id}" if task_id else ""
        logger.info("[DEBUG:%s]%s %s", category, suffix, data)
        try:
            path = os.path.join(_debug_dir(), f"{task_id or 'debug'}.log")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%H:%M:%S')} [{category}] {data}\n")
        except Exception:  # pragma: no cover - file dump is best-effort
            pass
    except Exception:  # pragma: no cover - never break the caller
        logger.debug("debug_dump failed", exc_info=True)
