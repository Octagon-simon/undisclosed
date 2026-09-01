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

"""Semantic emitters -- one function per lifecycle moment.

Call sites should use these instead of touching the dispatcher directly:
they pin down the exact flat payload fields each event carries (JSON scalars
only, per events.py's beckon-compatibility note) so adapters like beckon's
``eigent-hook`` can rely on the shape.
"""

from __future__ import annotations

from typing import Any

from app.hooks.dispatcher import fire_hook
from app.hooks.events import HookEvent


async def emit_permission_requested(
    *,
    task_id: str,
    tool_name: str,
    category: str,
    action_id: str,
    description: str = "",
    timeout_seconds: float | int | None = None,
    agent_name: str = "",
) -> None:
    """An Ask-mode mutating action is waiting for the user's decision."""
    data: dict[str, Any] = {
        "taskId": task_id,
        "actionId": action_id,
        "toolName": tool_name,
        "category": category,
        "description": description[:200],
        "agentName": agent_name or "single_agent",
    }
    if timeout_seconds is not None:
        data["timeoutSeconds"] = int(timeout_seconds)
    await fire_hook(HookEvent.permission_requested, **data)


async def emit_permission_resolved(
    event: HookEvent,
    *,
    task_id: str,
    action_id: str,
    tool_name: str,
    category: str,
    reason: str = "",
) -> None:
    """The user approved/denied a pending action, or it timed out."""
    if event not in (
        HookEvent.permission_approved,
        HookEvent.permission_denied,
        HookEvent.permission_timeout,
    ):
        raise ValueError(f"{event} is not a permission-resolution event")
    data = {
        "taskId": task_id,
        "actionId": action_id,
        "toolName": tool_name,
        "category": category,
    }
    if reason:
        # Flat scalar only; truncated like description above.
        data["reason"] = reason[:200]
    await fire_hook(event, **data)


def permission_requested_thread_safe(**kwargs: Any) -> None:
    from app.hooks.dispatcher import emit_event_thread_safe

    emit_event_thread_safe(HookEvent.permission_requested, **kwargs)


def permission_resolved_thread_safe(event: HookEvent, **kwargs: Any) -> None:
    from app.hooks.dispatcher import emit_event_thread_safe

    emit_event_thread_safe(event, **kwargs)


# ---------------------------------------------------------------------------
# Task lifecycle & session events
# ---------------------------------------------------------------------------


async def emit_task_started(*, task_id: str, agent_name: str = "") -> None:
    """A turn has begun executing."""
    await fire_hook(
        HookEvent.task_started,
        taskId=task_id,
        agentName=agent_name or "single_agent",
    )


async def emit_task_completed(*, task_id: str) -> None:
    """A turn finished successfully. Uses the beckon-known ``task_end``."""
    await fire_hook(HookEvent.task_end, taskId=task_id)


async def emit_task_failed(*, task_id: str, error: str = "") -> None:
    """A turn raised before producing a result."""
    await fire_hook(
        HookEvent.task_failed, taskId=task_id, error=str(error)[:200]
    )


async def emit_task_cancelled(*, task_id: str) -> None:
    """The user stopped or skipped the run."""
    await fire_hook(HookEvent.task_cancelled, taskId=task_id)


async def emit_session_paused(*, task_id: str) -> None:
    """The user paused the session (or took control)."""
    await fire_hook(HookEvent.session_paused, taskId=task_id)


async def emit_session_resumed(*, task_id: str) -> None:
    """The user resumed the session."""
    await fire_hook(HookEvent.session_resumed, taskId=task_id)
