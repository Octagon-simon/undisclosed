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

"""ApprovalManager: explicit human gating for risky tool executions.

Flow (all hook emissions are scheduled fire-and-forget so they can never add
latency to the tool executor or the HTTP request):

    request_approval(...)          # called from a gated tool (async, on the
                                    # main loop)
        |-> hooks.emit_permission_requested(...)
        |-> ActionApprovalRequestData  -> SSE stream (frontend prompt)
        `-> waits on an asyncio.Future (bounded by approval_timeout_s)

    resolve(approval_id, decision) # called from the HTTP layer
        |-> hooks.emit_permission_resolved(...)
        |-> ActionApprovalResolvedData -> SSE stream
        `-> wakes the waiting executor with approved / denied

Timeout resolves as "timeout"; a dying session cancels every waiter so
no tool can block forever against a gone stream.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

from app.hooks.emitters import (
    emit_permission_requested,
    emit_permission_resolved,
)
from app.hooks.events import HookEvent
from app.service.task import (
    ActionApprovalRequestData,
    ActionApprovalResolvedData,
    ApprovalRequestPayload,
    ApprovalResolvedPayload,
)
from app.utils.event_loop_utils import _schedule_async_task

logger = logging.getLogger(__name__)

VALID_DECISIONS = ("approved", "denied")

#: Single category for now - all gated tools are "mutating" actions.
_CATEGORY = "mutating"


@dataclass
class _PendingApproval:
    future: asyncio.Future[str]
    tool_name: str
    timeout_handle: asyncio.TimerHandle | None


class ApprovalManager:
    """One instance per task/session; stored on the TaskLock."""

    def __init__(
        self,
        task_lock,
        *,
        approval_timeout_s: float = 120.0,
    ) -> None:
        self._task_lock = task_lock
        self._timeout_s = float(approval_timeout_s)
        self._pending: dict[str, _PendingApproval] = {}

    # ------------------------------------------------------------------ #
    # Tool-executor side
    # ------------------------------------------------------------------ #

    async def request_approval(
        self,
        *,
        tool_name: str,
        detail: str = "",
        agent_name: str | None = None,
    ) -> str:
        """Block until a human approves/denies (or timeout). Returns the
        lowercase decision string."""
        loop = asyncio.get_running_loop()
        approval_id = uuid.uuid4().hex[:16]
        future: asyncio.Future[str] = loop.create_future()

        self._pending[approval_id] = _PendingApproval(
            future=future, tool_name=tool_name, timeout_handle=None
        )

        # 1. External observers (beckon etc.) hear about the request first
        #    so a notification lands before/with the UI prompt.
        _schedule_async_task(
            emit_permission_requested(
                task_id=self._current_task_id(),
                tool_name=tool_name,
                category=_CATEGORY,
                action_id=approval_id,
                description=detail,
                timeout_seconds=self._timeout_s,
                agent_name=agent_name or "",
            )
        )

        # 2. Queue the SSE prompt. Fire-and-forget scheduling keeps this
        #    safe from worker threads (put_queue is a coroutine).
        request_data = ActionApprovalRequestData(
            data=ApprovalRequestPayload(
                approval_id=approval_id,
                tool_name=tool_name,
                detail=detail,
                agent_name=agent_name,
            )
        )
        scheduled = _schedule_async_task(
            self._task_lock.put_queue(request_data)
        )
        if scheduled is None:
            logger.error(
                "No event loop available to surface approval request %s",
                approval_id,
            )

        # 3. Bound the wait.
        handle = loop.call_later(
            self._timeout_s, self._on_timeout, approval_id
        )
        self._pending[approval_id].timeout_handle = handle

        try:
            decision = await future
        except asyncio.CancelledError:
            logger.info(
                "Approval waiter cancelled mid-wait",
                extra={"approval_id": approval_id},
            )
            raise
        finally:
            self._clear_timeout(approval_id)

        return decision

    # ------------------------------------------------------------------ #
    # HTTP side
    # ------------------------------------------------------------------ #

    def resolve(
        self,
        approval_id: str,
        decision: str,
        *,
        decided_by: str | None = None,
    ) -> bool:
        """Deliver a human decision. Returns True if a waiter was woken.

        Thread-safe: may be called from any thread (FastAPI thread pool
        included); future completion hops onto the waiting loop.
        """
        normalized = (decision or "").strip().lower()
        if normalized == "approve":
            normalized = "approved"
        elif normalized == "deny":
            normalized = "denied"
        if normalized not in VALID_DECISIONS:
            raise ValueError(f"Invalid approval decision: {decision!r}")

        entry = self._pending.pop(approval_id, None)
        if entry is None:
            return False
        self._clear_timeout_entry(entry)

        task_id = self._current_task_id()
        event = (
            HookEvent.permission_approved
            if normalized == "approved"
            else HookEvent.permission_denied
        )
        _schedule_async_task(
            emit_permission_resolved(
                event,
                task_id=task_id,
                action_id=approval_id,
                tool_name=entry.tool_name,
                category=_CATEGORY,
                reason=decided_by or "",
            )
        )
        _schedule_async_task(
            self._task_lock.put_queue(
                ActionApprovalResolvedData(
                    data=ApprovalResolvedPayload(
                        approval_id=approval_id,
                        decision=normalized,
                        decided_by=decided_by,
                    )
                )
            )
        )

        self._wake_future(entry.future, normalized)
        return True

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def cancel_all(self, reason: str = "session ended") -> int:
        """Wake every pending waiter with CancelledError. Returns count."""
        count = 0
        for approval_id, entry in list(self._pending.items()):
            self._pending.pop(approval_id, None)
            self._clear_timeout_entry(entry)
            cancelled = entry.future.cancel()
            if cancelled:
                count += 1
        if count:
            logger.info(
                "Cancelled %d pending approval(s): %s",
                count,
                reason,
            )
        return count

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _current_task_id(self) -> str:
        current = getattr(self._task_lock, "current_task_id", None)
        return current or getattr(self._task_lock, "id", "")

    def _on_timeout(self, approval_id: str) -> None:
        entry = self._pending.pop(approval_id, None)
        if entry is None:
            return
        _schedule_async_task(
            emit_permission_resolved(
                HookEvent.permission_timeout,
                task_id=self._current_task_id(),
                action_id=approval_id,
                tool_name=entry.tool_name,
                category=_CATEGORY,
                reason="timeout",
            )
        )
        _schedule_async_task(
            self._task_lock.put_queue(
                ActionApprovalResolvedData(
                    data=ApprovalResolvedPayload(
                        approval_id=approval_id,
                        decision="timeout",
                        decided_by="timeout",
                    )
                )
            )
        )
        # Timeout means "not approved": wake the waiter deterministically
        # rather than leaving it hanging on a done-less future.
        if not entry.future.done():
            self._wake_future(entry.future, "timeout")

    def _wake_future(self, future: asyncio.Future[str], value: str) -> None:
        loop = future.get_loop()

        def _set() -> None:
            if not future.done():
                future.set_result(value)

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            _set()
        else:
            loop.call_soon_threadsafe(_set)

    def _clear_timeout(self, approval_id: str) -> None:
        entry = self._pending.get(approval_id)
        if entry is not None:
            self._clear_timeout_entry(entry)

    def _clear_timeout_entry(self, entry: _PendingApproval) -> None:
        handle = entry.timeout_handle
        if handle is not None:
            handle.cancel()
            entry.timeout_handle = None
