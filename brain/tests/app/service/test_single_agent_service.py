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

"""single_agent_service skip lifecycle regression tests."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def _parse_sse(line: str) -> tuple[str, object]:
    """Parse a `data: {...}\\n\\n` SSE line into (step, payload)."""

    assert line.startswith("data: "), line
    payload = json.loads(line[len("data: ") :].strip())
    return payload.get("step", ""), payload.get("data")


@pytest.mark.asyncio
async def test_skip_task_emits_end_without_blocking_on_cancellation():
    """R27-2 regression: pressing Skip while the turn is mid-flight in a
    non-cooperative coroutine (e.g. stuck inside a model HTTP call that does
    not propagate CancelledError) must still produce the user-facing "end"
    event promptly. The previous R26 fix added `await running_turn` after
    cancel(), which would block this generator until the turn actually
    finished cleaning up.
    """

    from app.model.chat import Chat
    from app.service.single_agent_service import single_agent_solve
    from app.service.task import (
        ActionImproveData,
        ActionSkipTaskData,
        ImprovePayload,
    )

    # A running_turn that ignores cancellation -- mimics a stuck model call.
    async def never_resolves():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            # Pretend the underlying tool swallowed the cancel; keep sleeping.
            await asyncio.sleep(60)
            raise

    # Fake agent whose astep returns the never-resolving coroutine.
    fake_agent = MagicMock()
    fake_agent.astep = lambda prompt: never_resolves()
    fake_agent.agent_id = "fake_single_agent"
    fake_agent._observable_todo_toolkit = None

    # Queue: improve action first, then skip after the turn is in flight.
    queue: asyncio.Queue = asyncio.Queue()

    improve_item = ActionImproveData(
        data=ImprovePayload(
            question="do something slow",
            attaches=[],
            project_context=None,
        ),
        new_task_id="task_skip",
    )
    skip_item = ActionSkipTaskData(project_id="project_skip")
    await queue.put(improve_item)

    task_lock = MagicMock()
    task_lock.id = "task_skip"
    task_lock.email = "u@example.com"
    task_lock.status = "OPEN"
    task_lock.conversation_history = []
    task_lock.last_task_result = ""
    task_lock.agent_memory_history = []
    task_lock.memory_summary = ""
    task_lock.summary_generated = False
    task_lock.run_context = None  # disables durable read

    async def get_queue():
        return await queue.get()

    task_lock.get_queue = get_queue
    task_lock.add_background_task = MagicMock()

    request = MagicMock()
    request.is_disconnected = AsyncMock(return_value=False)

    options = MagicMock(spec=Chat)
    options.project_id = "project_skip"
    options.task_id = "task_skip"
    options.project_context = None

    with (
        patch(
            "app.service.single_agent_service.single_agent",
            new=AsyncMock(return_value=fake_agent),
        ),
        patch("app.service.single_agent_service.set_current_task_id"),
        patch("app.service.single_agent_service.record_agent_memory_snapshot"),
        patch(
            "app.service.single_agent_service.build_memory_context",
            return_value="",
        ),
        patch("app.service.single_agent_service._finalize_memory_for_turn"),
        patch(
            "app.service.single_agent_service._build_single_agent_context",
            return_value="",
        ),
    ):
        agen = single_agent_solve(options, request, task_lock)

        # First frame: "confirmed" after the improve action lands.
        confirmed = await asyncio.wait_for(agen.__anext__(), timeout=3.0)
        event, _ = _parse_sse(confirmed)
        assert event == "confirmed", confirmed

        # The turn is now running and stuck. Send skip.
        await queue.put(skip_item)

        # Critical assertion: the "end" event arrives quickly, even though
        # the running_turn would block for ~60s. Use a tight 3s timeout --
        # before R27-2 this would hang at `await running_turn` until the
        # never-resolving coroutine completed.
        end_frame = await asyncio.wait_for(agen.__anext__(), timeout=3.0)
        event, payload = _parse_sse(end_frame)
        assert event == "end", end_frame
        assert "stopped by user" in str(payload).lower(), payload

        # Cleanup: close the generator so the underlying task gets cancelled
        # and pytest does not warn about pending tasks.
        await agen.aclose()


class TestActionToSse:
    """`_action_to_sse` must produce a real, `json.dumps`-able SSE frame for
    every Action variant. Regression for a bug where the approval actions'
    `.data` (a BaseModel, unlike every other action's plain dict/str) was
    passed straight to `sse_json`'s bare `json.dumps`, raising TypeError and
    silently killing the whole SSE generator -- which is why neither the
    approval card nor the Stop button worked: the generator that would have
    delivered the prompt (and kept consuming the queue for Stop) had already
    crashed before either could happen.
    """

    def test_approval_request_produces_valid_json(self):
        from app.service.single_agent_service import _action_to_sse
        from app.service.task import (
            ActionApprovalRequestData,
            ApprovalRequestPayload,
        )

        item = ActionApprovalRequestData(
            data=ApprovalRequestPayload(
                approval_id="abc123",
                tool_name="terminal",
                detail="shell_exec(command='docker --version')",
                agent_name="single_agent",
            )
        )

        frame = _action_to_sse(item)

        assert frame is not None
        payload = json.loads(frame.removeprefix("data: ").strip())
        assert payload["step"] == "approval_request"
        assert payload["data"]["approval_id"] == "abc123"
        assert payload["data"]["tool_name"] == "terminal"

    def test_approval_resolved_produces_valid_json(self):
        from app.service.single_agent_service import _action_to_sse
        from app.service.task import (
            ActionApprovalResolvedData,
            ApprovalResolvedPayload,
        )

        item = ActionApprovalResolvedData(
            data=ApprovalResolvedPayload(
                approval_id="abc123",
                decision="timeout",
                decided_by="timeout",
            )
        )

        frame = _action_to_sse(item)

        assert frame is not None
        payload = json.loads(frame.removeprefix("data: ").strip())
        assert payload["step"] == "approval_resolved"
        assert payload["data"]["decision"] == "timeout"


class TestAnnounceAndStopRecovery:
    """The turn loop must nudge a model that ends its turn on an intent-only
    preamble instead of doing the work / reporting results.

    Regression for the "4 in 8" stall: the low-temp model emits
    "I'll check … Let me start by …", the turn ends, and the user has to send
    "ok?" to resume. Two failure shapes are covered — zero-tool-call preamble,
    and (the one the old guard MISSED) a turn that ran tools but whose trailing
    segment was empty, so the last pre-tool-call preamble was resurrected as the
    final answer.
    """

    def test_detects_zero_tool_announce(self):
        from app.service.single_agent_service import _should_auto_continue

        stalled = (
            "I'll check the current branch state and what test coverage exists "
            "for each changed file."
        )
        assert _should_auto_continue(
            stalled,
            "some tests are missing from your changes. kindly check",
            tool_called=False,
            answer_from_fallback=False,
        )

    def test_detects_announce_after_tools_with_fallback_answer(self):
        from app.service.single_agent_service import _should_auto_continue

        # The exact stalled answer seen in .brain.log: tools ran (3 rounds) but
        # the trailing segment was empty, so this preamble was the "answer".
        stalled = (
            "I'll investigate which tests are missing. Let me start by checking "
            "the current state of the branch and what changed."
        )
        assert _should_auto_continue(
            stalled,
            "some tests are missing from your changes. kindly check",
            tool_called=True,
            answer_from_fallback=True,
        )

    def test_does_not_nudge_real_closing_answer_after_tools(self):
        from app.service.single_agent_service import _should_auto_continue

        # Tools ran and the model DID write a trailing message — never nudge,
        # even if it happens to contain "I'll".
        real = "Added 3 tests. I'll push once you approve."
        assert not _should_auto_continue(
            real,
            "add tests for the new files",
            tool_called=True,
            answer_from_fallback=False,
        )

    def test_does_not_nudge_chat_or_long_answers(self):
        from app.service.single_agent_service import _should_auto_continue

        # Chit-chat is never nudged.
        assert not _should_auto_continue(
            "I'll do that!",
            "hi",
            tool_called=False,
            answer_from_fallback=False,
        )
        # A substantive answer isn't an announce-and-stop.
        long_answer = "Let me walk through the findings. " + ("x" * 500)
        assert not _should_auto_continue(
            long_answer,
            "explain the bug",
            tool_called=False,
            answer_from_fallback=False,
        )

    def test_empty_content_never_nudges(self):
        from app.service.single_agent_service import _should_auto_continue

        assert not _should_auto_continue(
            "", "do the thing", tool_called=False, answer_from_fallback=True
        )

    def test_real_answer_is_kept_when_fallback_but_substantive(self):
        from app.service.single_agent_service import (
            _looks_like_announce_and_stop,
        )

        # A model that writes its answer just before a final tool call: the
        # fallback resurrects it, but it is NOT narration, so no nudge.
        answer = (
            "## Summary\n"
            "I fixed the receipt `+` sign and added coverage for "
            "TransactionsTable, RecentTransactions, and useTransactionDetail."
        )
        assert not _looks_like_announce_and_stop(answer, "fix the tests")

