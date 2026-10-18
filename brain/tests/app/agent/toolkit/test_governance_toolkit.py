# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
# Portions Copyright 2026 Simon Ugorji. All Rights Reserved.
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

"""Tests for the approval-gating governance toolkit.

Covers `GovernanceMode` coercion and the `wrap_with_approval` wrapper:
schema preservation, approve/deny/timeout handling, rejection-as-string
feedback, and fail-closed guards when the live `ApprovalManager` is
unavailable.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from camel.toolkits import FunctionTool

from app.agent.toolkit.command_policy import CommandScope, CommandTier
from app.agent.toolkit.governance_toolkit import (
    DENIED_DECISIONS,
    GovernanceMode,
    _call_tier,
    wrap_with_approval,
)

pytestmark = pytest.mark.unit


async def _sample_tool(path: str) -> str:
    """Write to a file.

    Args:
        path: The file path.
    """
    return f"wrote {path}"


def _make_tool() -> FunctionTool:
    return FunctionTool(_sample_tool)


async def _shell_tool(command: str) -> str:
    """Run a shell command.

    Args:
        command: The command line.
    """
    return f"ran {command}"


def _make_shell_tool() -> FunctionTool:
    return FunctionTool(_shell_tool)


def _patch_manager(
    monkeypatch,
    decision: str = "approved",
    allowed_scopes: set[str] | None = None,
):
    manager = MagicMock()
    manager.request_approval = AsyncMock(return_value=decision)
    task_lock = MagicMock()
    task_lock.approval_manager = manager
    if allowed_scopes is not None:
        task_lock.allowed_approval_scopes = lambda: set(allowed_scopes)
    monkeypatch.setattr(
        "app.agent.toolkit.governance_toolkit.get_task_lock",
        lambda project_id: task_lock,
    )
    return manager


class TestGovernanceModeCoerce:
    @pytest.mark.parametrize(
        "raw", ["ask", "ASK", "always", "manual", "human"]
    )
    def test_recognized_ask_aliases(self, raw):
        assert GovernanceMode.coerce(raw) is GovernanceMode.ASK

    @pytest.mark.parametrize("raw", [None, "", "auto", "off", 123, {}])
    def test_unknown_or_auto_falls_back_to_auto(self, raw):
        assert GovernanceMode.coerce(raw) is GovernanceMode.AUTO

    def test_passthrough_of_enum_value(self):
        assert GovernanceMode.coerce(GovernanceMode.ASK) is GovernanceMode.ASK


class TestWrapWithApproval:
    def test_wrapped_tool_preserves_schema(self):
        tool = _make_tool()
        original_name = tool.get_function_name()
        original_schema = tool.openai_tool_schema

        gated = wrap_with_approval(
            tool,
            field_name="file_write",
            agent_name="single_agent",
            api_task_id="project_1",
        )

        assert gated.get_function_name() == original_name
        assert gated.openai_tool_schema == original_schema

    @pytest.mark.asyncio
    async def test_approved_call_runs_underlying_tool(self, monkeypatch):
        tool = _make_tool()
        gated = wrap_with_approval(
            tool,
            field_name="file_write",
            agent_name="single_agent",
            api_task_id="project_1",
        )

        manager = MagicMock()
        manager.request_approval = AsyncMock(return_value="approved")
        task_lock = MagicMock()
        task_lock.approval_manager = manager
        monkeypatch.setattr(
            "app.agent.toolkit.governance_toolkit.get_task_lock",
            lambda project_id: task_lock,
        )

        result = await gated.func(path="notes.txt")
        assert result == "wrote notes.txt"
        manager.request_approval.assert_awaited_once()
        assert manager.request_approval.await_args.kwargs["tool_name"] == (
            "file_write"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("decision", sorted(DENIED_DECISIONS))
    async def test_denied_or_timeout_call_short_circuits(
        self, monkeypatch, decision
    ):
        tool = _make_tool()
        gated = wrap_with_approval(
            tool,
            field_name="file_write",
            agent_name="single_agent",
            api_task_id="project_1",
        )

        manager = MagicMock()
        manager.request_approval = AsyncMock(return_value=decision)
        task_lock = MagicMock()
        task_lock.approval_manager = manager
        monkeypatch.setattr(
            "app.agent.toolkit.governance_toolkit.get_task_lock",
            lambda project_id: task_lock,
        )

        result = await gated.func(path="notes.txt")
        assert "[SYSTEM GOVERNANCE]" in result
        assert "_sample_tool" in result
        manager.request_approval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missing_task_lock_fails_closed(self, monkeypatch):
        tool = _make_tool()
        gated = wrap_with_approval(
            tool,
            field_name="file_write",
            agent_name="single_agent",
            api_task_id="project_1",
        )

        def _raise(project_id):
            raise KeyError(project_id)

        monkeypatch.setattr(
            "app.agent.toolkit.governance_toolkit.get_task_lock", _raise
        )

        result = await gated.func(path="notes.txt")
        assert "[SYSTEM GOVERNANCE]" in result
        assert "gate unavailable" in result

    @pytest.mark.asyncio
    async def test_missing_approval_manager_fails_closed(self, monkeypatch):
        tool = _make_tool()
        gated = wrap_with_approval(
            tool,
            field_name="file_write",
            agent_name="single_agent",
            api_task_id="project_1",
        )

        task_lock = MagicMock()
        task_lock.approval_manager = None
        monkeypatch.setattr(
            "app.agent.toolkit.governance_toolkit.get_task_lock",
            lambda project_id: task_lock,
        )

        result = await gated.func(path="notes.txt")
        assert "[SYSTEM GOVERNANCE]" in result
        assert "not initialised" in result


class TestTieredGating:
    def _gated(self, mode, field_name="terminal"):
        return wrap_with_approval(
            _make_shell_tool(),
            field_name=field_name,
            agent_name="single_agent",
            api_task_id="project_1",
            mode=mode,
        )

    @pytest.mark.asyncio
    async def test_read_only_skips_prompt_in_ask(self, monkeypatch):
        manager = _patch_manager(monkeypatch)
        gated = self._gated(GovernanceMode.ASK)

        assert await gated.func(command="git status") == "ran git status"
        manager.request_approval.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_workspace_write_skips_prompt_in_auto(self, monkeypatch):
        manager = _patch_manager(monkeypatch)
        gated = self._gated(GovernanceMode.AUTO)

        assert await gated.func(command="mkdir out") == "ran mkdir out"
        manager.request_approval.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_workspace_write_prompts_in_ask(self, monkeypatch):
        manager = _patch_manager(monkeypatch)
        gated = self._gated(GovernanceMode.ASK)

        assert await gated.func(command="mkdir out") == "ran mkdir out"
        manager.request_approval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_destructive_prompts_in_auto(self, monkeypatch):
        manager = _patch_manager(monkeypatch)
        gated = self._gated(GovernanceMode.AUTO)

        result = await gated.func(command="git push origin main")
        assert result == "ran git push origin main"
        manager.request_approval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_destructive_denied_in_auto(self, monkeypatch):
        _patch_manager(monkeypatch, decision="denied")
        gated = self._gated(GovernanceMode.AUTO)

        result = await gated.func(command="git push origin main")
        assert "[SYSTEM GOVERNANCE]" in result

    @pytest.mark.asyncio
    async def test_blocked_never_prompts_and_never_runs(self, monkeypatch):
        manager = _patch_manager(monkeypatch)
        gated = self._gated(GovernanceMode.AUTO)

        result = await gated.func(command="rm -rf build")
        assert "blocked by policy" in result
        assert result != "ran rm -rf build"
        manager.request_approval.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_command_can_be_positional(self, monkeypatch):
        manager = _patch_manager(monkeypatch)
        gated = self._gated(GovernanceMode.AUTO)

        assert await gated.func("git status") == "ran git status"
        manager.request_approval.assert_not_awaited()


class TestCallTier:
    def test_shell_command_from_kwargs(self):
        assert _call_tier(
            "terminal", "shell_exec", (), {"command": "git status"}
        ) == CommandTier.READ_ONLY

    def test_shell_command_from_positional(self):
        assert _call_tier(
            "terminal", "shell_exec", ("git push",), {}
        ) == CommandTier.DESTRUCTIVE

    def test_non_shell_write_is_tier_one(self):
        assert _call_tier(
            "file_write", "write_to_file", (), {"path": "a.txt"}
        ) == CommandTier.WORKSPACE_WRITE

    def test_external_write_is_destructive(self):
        assert _call_tier(
            "github_write", "create_issue", (), {}
        ) == CommandTier.DESTRUCTIVE


async def git_push(branch: str) -> str:
    """Push a branch.

    Args:
        branch: The branch to push.
    """
    return f"pushed {branch}"


def _make_git_push_tool() -> FunctionTool:
    return FunctionTool(git_push)


class TestTaskAllowlist:
    def _gated(self, mode, field_name="terminal"):
        return wrap_with_approval(
            _make_shell_tool(),
            field_name=field_name,
            agent_name="single_agent",
            api_task_id="project_1",
            mode=mode,
        )

    @pytest.mark.asyncio
    async def test_reads_are_allowed_by_default(self, monkeypatch):
        manager = _patch_manager(monkeypatch)
        gated = self._gated(GovernanceMode.AUTO)

        assert await gated.func(command="git status") == "ran git status"
        manager.request_approval.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reads_prompt_when_file_reads_is_removed(self, monkeypatch):
        manager = _patch_manager(monkeypatch, allowed_scopes=set())
        gated = self._gated(GovernanceMode.AUTO)

        assert await gated.func(command="git status") == "ran git status"
        manager.request_approval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_workspace_write_is_suppressed_in_ask(self, monkeypatch):
        manager = _patch_manager(
            monkeypatch,
            allowed_scopes={CommandScope.FILE_WRITES.value},
        )
        gated = self._gated(GovernanceMode.ASK)

        assert await gated.func(command="mkdir out") == "ran mkdir out"
        manager.request_approval.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unrelated_scope_does_not_suppress_a_write(self, monkeypatch):
        manager = _patch_manager(
            monkeypatch,
            allowed_scopes={CommandScope.BUILDS_TESTS.value},
        )
        gated = self._gated(GovernanceMode.ASK)

        await gated.func(command="mkdir out")
        manager.request_approval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_destructive_is_never_suppressed(self, monkeypatch):
        manager = _patch_manager(
            monkeypatch,
            allowed_scopes={scope.value for scope in CommandScope},
        )
        gated = self._gated(GovernanceMode.AUTO)

        await gated.func(command="git push origin main")
        manager.request_approval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_request_carries_tier_and_scope(self, monkeypatch):
        manager = _patch_manager(monkeypatch, allowed_scopes=set())
        gated = self._gated(GovernanceMode.ASK)

        await gated.func(command="mkdir out")
        kwargs = manager.request_approval.await_args.kwargs
        assert kwargs["tier"] == int(CommandTier.WORKSPACE_WRITE)
        assert kwargs["tier_label"] == "Writes files"
        assert kwargs["scopes"] == [CommandScope.FILE_WRITES.value]
        assert "workspace" in kwargs["description"]

    @pytest.mark.asyncio
    async def test_git_push_is_destructive_through_git_write(self, monkeypatch):
        manager = _patch_manager(monkeypatch)
        gated = wrap_with_approval(
            _make_git_push_tool(),
            field_name="git_write",
            agent_name="single_agent",
            api_task_id="project_1",
            mode=GovernanceMode.AUTO,
        )

        await gated.func(branch="main")
        manager.request_approval.assert_awaited_once()
        kwargs = manager.request_approval.await_args.kwargs
        assert kwargs["tier"] == int(CommandTier.DESTRUCTIVE)
        assert kwargs["scopes"] == []
