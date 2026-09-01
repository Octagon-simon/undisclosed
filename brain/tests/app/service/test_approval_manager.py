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

"""Tests for ApprovalManager: approve / deny / timeout / cancel paths, SSE
queue pushes, and permission hook emissions."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.hooks.events import HookEvent
from app.service.approval_manager import ApprovalManager
from app.service.task import (
    ActionApprovalRequestData,
    ActionApprovalResolvedData,
)

pytestmark = pytest.mark.unit


def _fake_task_lock():
    task_lock = MagicMock()
    task_lock.id = "project_1"
    task_lock.current_task_id = "task_1"
    task_lock.put_queue = AsyncMock()
    return task_lock


@pytest.fixture(autouse=True)
def _patch_emitters(monkeypatch):
    """Replace the hook emitters with AsyncMocks so tests assert on call
    shape instead of actually spawning subprocesses."""
    requested = AsyncMock()
    resolved = AsyncMock()
    monkeypatch.setattr(
        "app.service.approval_manager.emit_permission_requested", requested
    )
    monkeypatch.setattr(
        "app.service.approval_manager.emit_permission_resolved", resolved
    )
    return requested, resolved


class TestRequestApprove:
    @pytest.mark.asyncio
    async def test_approve_resolves_request_approval(self, _patch_emitters):
        task_lock = _fake_task_lock()
        manager = ApprovalManager(task_lock, approval_timeout_s=5)

        request_task = asyncio.create_task(
            manager.request_approval(tool_name="terminal", detail="ls -la")
        )
        # Let request_approval register the pending entry before resolving.
        await asyncio.sleep(0)
        assert manager.pending_count == 1

        (approval_id,) = list(manager._pending.keys())
        resolved = manager.resolve(approval_id, "approve", decided_by="user_1")
        assert resolved is True

        decision = await request_task
        assert decision == "approved"
        assert manager.pending_count == 0

    @pytest.mark.asyncio
    async def test_deny_resolves_request_approval(self, _patch_emitters):
        task_lock = _fake_task_lock()
        manager = ApprovalManager(task_lock, approval_timeout_s=5)

        request_task = asyncio.create_task(
            manager.request_approval(tool_name="file_write")
        )
        await asyncio.sleep(0)
        (approval_id,) = list(manager._pending.keys())

        assert manager.resolve(approval_id, "deny") is True
        assert await request_task == "denied"

    @pytest.mark.asyncio
    async def test_request_approval_pushes_request_then_resolved_to_queue(
        self, _patch_emitters
    ):
        task_lock = _fake_task_lock()
        manager = ApprovalManager(task_lock, approval_timeout_s=5)

        request_task = asyncio.create_task(
            manager.request_approval(tool_name="terminal", detail="ls")
        )
        await asyncio.sleep(0)
        (approval_id,) = list(manager._pending.keys())
        manager.resolve(approval_id, "approved")
        await request_task
        # request_approval schedules put_queue via _schedule_async_task
        # (create_task on this same running loop); let it run.
        await asyncio.sleep(0)

        calls = task_lock.put_queue.call_args_list
        assert len(calls) == 2
        assert isinstance(calls[0].args[0], ActionApprovalRequestData)
        assert calls[0].args[0].data.approval_id == approval_id
        assert isinstance(calls[1].args[0], ActionApprovalResolvedData)
        assert calls[1].args[0].data.decision == "approved"

    @pytest.mark.asyncio
    async def test_request_approval_fires_permission_requested_hook(
        self, _patch_emitters
    ):
        requested, _resolved = _patch_emitters
        task_lock = _fake_task_lock()
        manager = ApprovalManager(task_lock, approval_timeout_s=5)

        request_task = asyncio.create_task(
            manager.request_approval(
                tool_name="terminal",
                detail="ls -la",
                agent_name="single_agent",
            )
        )
        await asyncio.sleep(0)
        (approval_id,) = list(manager._pending.keys())
        manager.resolve(approval_id, "approved")
        await request_task
        await asyncio.sleep(0)

        requested.assert_awaited_once()
        kwargs = requested.await_args.kwargs
        assert kwargs["task_id"] == "task_1"
        assert kwargs["tool_name"] == "terminal"
        assert kwargs["action_id"] == approval_id
        assert kwargs["agent_name"] == "single_agent"

    @pytest.mark.asyncio
    async def test_resolve_fires_permission_approved_or_denied_hook(
        self, _patch_emitters
    ):
        _requested, resolved = _patch_emitters
        task_lock = _fake_task_lock()
        manager = ApprovalManager(task_lock, approval_timeout_s=5)

        request_task = asyncio.create_task(
            manager.request_approval(tool_name="terminal")
        )
        await asyncio.sleep(0)
        (approval_id,) = list(manager._pending.keys())
        manager.resolve(approval_id, "denied", decided_by="user_1")
        await request_task
        await asyncio.sleep(0)

        resolved.assert_awaited_once()
        args, kwargs = resolved.await_args
        assert args[0] == HookEvent.permission_denied
        assert kwargs["action_id"] == approval_id
        assert kwargs["reason"] == "user_1"


class TestResolveEdgeCases:
    def test_resolve_unknown_approval_id_returns_false(self):
        manager = ApprovalManager(_fake_task_lock())
        assert manager.resolve("does-not-exist", "approved") is False

    def test_resolve_invalid_decision_raises(self):
        manager = ApprovalManager(_fake_task_lock())
        with pytest.raises(ValueError):
            manager.resolve("whatever", "maybe")

    @pytest.mark.asyncio
    async def test_resolve_is_idempotent_after_first_decision(
        self, _patch_emitters
    ):
        task_lock = _fake_task_lock()
        manager = ApprovalManager(task_lock, approval_timeout_s=5)
        request_task = asyncio.create_task(
            manager.request_approval(tool_name="terminal")
        )
        await asyncio.sleep(0)
        (approval_id,) = list(manager._pending.keys())

        assert manager.resolve(approval_id, "approved") is True
        assert manager.resolve(approval_id, "denied") is False
        assert await request_task == "approved"


class TestTimeout:
    @pytest.mark.asyncio
    async def test_request_approval_times_out(self, _patch_emitters):
        task_lock = _fake_task_lock()
        manager = ApprovalManager(task_lock, approval_timeout_s=0.05)

        decision = await manager.request_approval(tool_name="terminal")
        assert decision == "timeout"
        assert manager.pending_count == 0

    @pytest.mark.asyncio
    async def test_timeout_fires_permission_timeout_hook(
        self, _patch_emitters
    ):
        _requested, resolved = _patch_emitters
        task_lock = _fake_task_lock()
        manager = ApprovalManager(task_lock, approval_timeout_s=0.05)

        await manager.request_approval(tool_name="terminal")
        # The timeout callback schedules the hook emission as a task on this
        # same loop; a single sleep(0) only yields one tick, which races
        # against how many hops the scheduled task needs, so poll briefly
        # instead of asserting after a fixed number of ticks.
        for _ in range(50):
            if resolved.await_count:
                break
            await asyncio.sleep(0.001)

        resolved.assert_awaited_once()
        args, kwargs = resolved.await_args
        assert args[0] == HookEvent.permission_timeout
        assert kwargs["reason"] == "timeout"


class TestCancelAll:
    @pytest.mark.asyncio
    async def test_cancel_all_wakes_pending_waiters_with_cancelled(
        self, _patch_emitters
    ):
        task_lock = _fake_task_lock()
        manager = ApprovalManager(task_lock, approval_timeout_s=5)

        request_task = asyncio.create_task(
            manager.request_approval(tool_name="terminal")
        )
        await asyncio.sleep(0)
        assert manager.pending_count == 1

        cancelled_count = manager.cancel_all(reason="session ended")
        assert cancelled_count == 1
        assert manager.pending_count == 0

        with pytest.raises(asyncio.CancelledError):
            await request_task

    def test_cancel_all_on_empty_manager_returns_zero(self):
        manager = ApprovalManager(_fake_task_lock())
        assert manager.cancel_all() == 0
