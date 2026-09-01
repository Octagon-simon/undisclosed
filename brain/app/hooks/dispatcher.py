# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========

"""Hook dispatcher.

Runs user-configured commands with a JSON event payload on stdin -- the same
contract as the original ``EIGENT_NOTIFY_COMMAND`` patch (see
documents/github/beckon README + EXTENDING.md): fire-and-forget from the
caller's perspective, short timeout, silent on failure.

Invariants (all inherited from notify.py's contract):
- Missing configuration is a no-op (resolved before any subprocess work).
- A missing binary, non-zero exit, stderr output, or timeout is swallowed at
  debug level; one hook failing never affects the task or other hooks.
- Callers schedule this rather than awaiting it inline so a slow hook can
  never add latency to agent execution paths.

Environment:
    EIGENT_HOOKS            JSON object: {event|* : command | [commands]}
    EIGENT_HOOK_TIMEOUT_MS  Per-hook timeout in ms (default 2000)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from app.hooks.config import is_configured, resolve_commands_for_event
from app.hooks.events import HookEvent, build_payload, event_name

logger = logging.getLogger("hooks.dispatcher")

DEFAULT_HOOK_TIMEOUT_SECONDS = 2.0


def get_hook_timeout() -> float:
    """Per-command timeout in seconds, overridable via EIGENT_HOOK_TIMEOUT_MS."""
    raw = os.environ.get("EIGENT_HOOK_TIMEOUT_MS", "").strip()
    if not raw:
        return DEFAULT_HOOK_TIMEOUT_SECONDS
    try:
        ms = float(raw)
    except ValueError:
        logger.warning("Invalid EIGENT_HOOK_TIMEOUT_MS=%r; using default", raw)
        return DEFAULT_HOOK_TIMEOUT_SECONDS
    if ms <= 0:
        return DEFAULT_HOOK_TIMEOUT_SECONDS
    return ms / 1000.0


async def run_hook_command(command: str, payload: dict[str, Any]) -> None:
    """Run one hook command with the payload JSON on stdin. Never raises."""
    encoded = json.dumps(payload).encode("utf-8")
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except Exception:
        logger.debug(
            "Hook command failed to start: %s", command, exc_info=True
        )
        return

    try:
        await asyncio.wait_for(
            process.communicate(encoded),
            timeout=get_hook_timeout(),
        )
    except TimeoutError:
        process.kill()
    except Exception:
        logger.debug("Hook command failed: %s", command, exc_info=True)


async def dispatch_payload(
    commands: list[str], payload: dict[str, Any]
) -> None:
    """Fan out one payload to every configured command, concurrently."""
    if not commands:
        return
    results = await asyncio.gather(
        *(run_hook_command(command, payload) for command in commands),
        return_exceptions=True,
    )
    failures = [r for r in results if isinstance(r, BaseException)]
    if failures:
        logger.debug(
            "%d/%d hook command(s) raised unexpectedly during fan-out",
            len(failures),
            len(results),
        )


async def fire_hook(event: HookEvent | str, **data: Any) -> None:
    """Fire an event to all configured hooks.

    Never raises, and returns immediately when nothing is configured.
    Prefer scheduling this via ``asyncio.create_task(fire_hook(...))`` (or the
    thread-safe :func:`emit_event_thread_safe`) rather than awaiting it
    inline -- same discipline as the original fire_notify call sites.
    """
    try:
        commands = resolve_commands_for_event(event)
        if not commands:
            return
        await dispatch_payload(commands, build_payload(event, data))
    except Exception:
        logger.debug(
            "fire_hook failed for event %r", event_name(event), exc_info=True
        )


def emit_event_thread_safe(event: HookEvent | str, **data: Any) -> None:
    """Schedule fire_hook on the registered main loop. Safe from any thread.

    Mirrors how workforce.py schedules fire_notify from worker threads via
    ``_schedule_async_task``. If no loop is registered (backend shutting
    down, early startup), the coroutine is closed quietly and dropped --
    hooks are strictly best-effort.
    """
    coro = fire_hook(event, **data)
    try:
        scheduled = _schedule_async_task(coro)
    except Exception:
        close_quietly(coro)
        logger.debug(
            "Could not schedule hook event %r",
            event_name(event),
            exc_info=True,
        )
        return
    if scheduled is None:
        close_quietly(coro)
        logger.debug(
            "No event loop registered; hook event %r dropped",
            event_name(event),
        )


def _schedule_async_task(coro):
    """Thin indirection so tests can patch this module's symbol."""
    from app.utils.event_loop_utils import _schedule_async_task as impl

    return impl(coro)


def _registered_main_loop():
    from app.utils.event_loop_utils import _get_registered_main_loop

    return _get_registered_main_loop()


def close_quietly(coro) -> None:
    close = getattr(coro, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


__all__ = [
    "DEFAULT_HOOK_TIMEOUT_SECONDS",
    "dispatch_payload",
    "emit_event_thread_safe",
    "fire_hook",
    "get_hook_timeout",
    "is_configured",
    "run_hook_command",
]
