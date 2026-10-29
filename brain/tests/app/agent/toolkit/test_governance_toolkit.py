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

import copy
from unittest.mock import AsyncMock, MagicMock

import pytest
from camel.toolkits import FunctionTool

from app.agent.toolkit.command_policy import CommandScope, CommandTier
from app.agent.toolkit.governance_toolkit import (
    DENIED_DECISIONS,
    GovernanceMode,
    _call_scopes,
    _call_tier,
    _normalize_intent,
    _test_runner_command,
    _with_intent_argument,
    gate_worker_tools,
    mode_from_toolkit_config,
    record_session_governance_mode,
    session_governance_mode,
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


async def delete_files(paths: list[str]) -> str:
    """Delete files.

    Args:
        paths: The paths to delete.
    """
    return f"deleted {paths}"


def _make_delete_tool() -> FunctionTool:
    return FunctionTool(delete_files)


def _without_intent(schema: dict) -> dict:
    cloned = copy.deepcopy(schema)
    cloned["function"]["parameters"]["properties"].pop("intent", None)
    return cloned


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
        original_properties = tool.openai_tool_schema["function"]["parameters"][
            "properties"
        ]
        gated_properties = gated.openai_tool_schema["function"]["parameters"][
            "properties"
        ]
        assert "intent" not in original_properties
        assert gated_properties["intent"]["type"] == "string"
        assert _without_intent(gated.openai_tool_schema) == original_schema

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
    async def test_outside_workspace_write_runs_in_auto(self, monkeypatch):
        manager = _patch_manager(monkeypatch)
        monkeypatch.setattr(
            "app.agent.toolkit.governance_toolkit.workspace_for_task",
            lambda task_id: "/repo",
        )
        gated = self._gated(GovernanceMode.AUTO)

        command = "node build.js > /tmp/build.log 2>&1"
        assert await gated.func(command=command) == f"ran {command}"
        manager.request_approval.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_outside_workspace_write_prompts_in_ask(self, monkeypatch):
        manager = _patch_manager(monkeypatch)
        monkeypatch.setattr(
            "app.agent.toolkit.governance_toolkit.workspace_for_task",
            lambda task_id: "/repo",
        )
        gated = self._gated(GovernanceMode.ASK)

        await gated.func(command="node build.js > /tmp/build.log 2>&1")
        manager.request_approval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_tool_prompts_in_auto(self, monkeypatch):
        manager = _patch_manager(monkeypatch)
        gated = wrap_with_approval(
            _make_delete_tool(),
            field_name="file_write",
            agent_name="single_agent",
            api_task_id="project_1",
            mode=GovernanceMode.AUTO,
        )

        await gated.func(paths=["build"])
        manager.request_approval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_file_write_skips_prompt_in_auto(self, monkeypatch):
        manager = _patch_manager(monkeypatch)
        gated = wrap_with_approval(
            _make_tool(),
            field_name="file_write",
            agent_name="single_agent",
            api_task_id="project_1",
            mode=GovernanceMode.AUTO,
        )

        assert await gated.func(path="notes.txt") == "wrote notes.txt"
        manager.request_approval.assert_not_awaited()

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


class _FakeTestRunner:
    def __init__(self, command: str) -> None:
        self.command = command

    def governance_command(self) -> str:
        return self.command

    async def run_tests(self, scope: str = "", base: str = "") -> str:
        """Run the suite with coverage.

        Args:
            scope: Coverage scope.
            base: Base branch.
        """
        return f"ran {self.command}"


class TestTestRunnerGate:
    """The coverage tools shell out, so they go through the command policy."""

    def _tool(self, command: str) -> FunctionTool:
        return FunctionTool(_FakeTestRunner(command).run_tests)

    def test_command_is_read_from_the_toolkit(self):
        assert _test_runner_command(self._tool("pytest -q")) == "pytest -q"

    def test_suite_runs_never_drop_below_workspace_write(self):
        assert (
            _call_tier(
                "test_runner", "run_tests", (), {}, tool_command="pytest -q"
            )
            == CommandTier.WORKSPACE_WRITE
        )

    def test_destructive_command_keeps_its_tier(self):
        assert (
            _call_tier(
                "test_runner",
                "run_tests",
                (),
                {},
                tool_command="git push origin main",
            )
            == CommandTier.DESTRUCTIVE
        )

    def test_blocked_command_stays_blocked(self):
        assert (
            _call_tier(
                "test_runner", "run_tests", (), {}, tool_command="rm -rf /"
            )
            == CommandTier.BLOCKED
        )

    def test_scopes_come_from_the_command(self):
        assert _call_scopes(
            "test_runner",
            "coverage_gap_plan",
            (),
            {},
            tool_command="pytest -q --cov",
        ) == (CommandScope.BUILDS_TESTS,)

    @pytest.mark.asyncio
    async def test_ask_prompts_with_the_resolved_command(self, monkeypatch):
        manager = _patch_manager(monkeypatch, allowed_scopes=set())
        gated = wrap_with_approval(
            self._tool("pytest -q --cov"),
            field_name="test_runner",
            agent_name="single_agent",
            api_task_id="project_1",
            mode=GovernanceMode.ASK,
        )

        await gated.func(scope="", base="")

        manager.request_approval.assert_awaited_once()
        kwargs = manager.request_approval.await_args.kwargs
        assert kwargs["tier"] == int(CommandTier.WORKSPACE_WRITE)
        assert kwargs["scopes"] == [CommandScope.BUILDS_TESTS.value]
        assert "pytest -q --cov" in kwargs["detail"]

    @pytest.mark.asyncio
    async def test_blocked_command_never_prompts_and_never_runs(
        self, monkeypatch
    ):
        manager = _patch_manager(monkeypatch)
        gated = wrap_with_approval(
            self._tool("rm -rf /"),
            field_name="test_runner",
            agent_name="single_agent",
            api_task_id="project_1",
            mode=GovernanceMode.AUTO,
        )

        result = await gated.func()

        assert "blocked by policy" in result
        manager.request_approval.assert_not_awaited()


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
        gated = self._gated(GovernanceMode.ASK)

        assert await gated.func(command="git status") == "ran git status"
        manager.request_approval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_build_command_does_not_prompt_when_scope_is_allowed(
        self, monkeypatch
    ):
        # Regression: pytest is read-only with a builds/tests scope, so the
        # privacy switch used to force an approval even under Auto.
        manager = _patch_manager(
            monkeypatch,
            allowed_scopes={
                CommandScope.FILE_READS.value,
                CommandScope.BUILDS_TESTS.value,
            },
        )
        gated = self._gated(GovernanceMode.AUTO)

        assert await gated.func(command="pytest -q") == "ran pytest -q"
        manager.request_approval.assert_not_awaited()

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
    async def test_heredoc_code_run_is_suppressed_by_runs_code(
        self, monkeypatch
    ):
        # Regression: the heredoc body used to be parsed as extra shell
        # commands, adding File writes / Builds & tests to the call. Selecting
        # only "Runs code" could then never suppress it.
        command = (
            "cat > /tmp/shot.cjs <<'EOF'\n"
            "const { chromium } = require('playwright');\n"
            "EOF\n"
            "node /tmp/shot.cjs"
        )
        manager = _patch_manager(
            monkeypatch,
            allowed_scopes={
                CommandScope.FILE_READS.value,
                CommandScope.CODE_EXECUTION.value,
            },
        )
        gated = self._gated(GovernanceMode.ASK)

        assert await gated.func(command=command) == f"ran {command}"
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
        assert kwargs["tier_label"] == "May change files"
        assert kwargs["scopes"] == [CommandScope.FILE_WRITES.value]
        assert "workspace" in kwargs["description"]

    @pytest.mark.asyncio
    async def test_request_explains_intent_and_keeps_long_command(
        self, monkeypatch
    ):
        manager = _patch_manager(monkeypatch, allowed_scopes=set())
        gated = self._gated(GovernanceMode.ASK)
        command = (
            "cd /tmp && node -v && echo start && node build.js --target "
            "production --out-dir dist --verbose --sourcemap"
        )

        await gated.func(command=command)
        kwargs = manager.request_approval.await_args.kwargs

        assert "The agent will check the node version" in kwargs["description"]
        assert "run a JavaScript script" in kwargs["description"]
        assert CommandScope.FILE_WRITES.value not in kwargs["scopes"]
        assert CommandScope.CODE_EXECUTION.value in kwargs["scopes"]
        # The old 200-char cap cut the tail of the command.
        assert command in kwargs["detail"]
        assert "..." not in kwargs["detail"]

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

    @pytest.mark.asyncio
    async def test_cd_prefix_does_not_force_a_prompt(self, monkeypatch):
        manager = _patch_manager(
            monkeypatch,
            allowed_scopes={CommandScope.FILE_READS.value},
        )
        gated = self._gated(GovernanceMode.ASK)

        command = "cd /repo && ls"
        assert await gated.func(command=command) == f"ran {command}"
        manager.request_approval.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_listing_card_says_reads_only(self, monkeypatch):
        manager = _patch_manager(monkeypatch, allowed_scopes=set())
        gated = self._gated(GovernanceMode.ASK)

        await gated.func(command="cd /repo && find . -name '*.py'")
        kwargs = manager.request_approval.await_args.kwargs
        assert kwargs["tier"] == int(CommandTier.READ_ONLY)
        assert kwargs["tier_label"] == "Read only"
        assert kwargs["scopes"] == [CommandScope.FILE_READS.value]
        assert kwargs["description"].endswith(
            "It only reads your workspace."
        )
        assert "search for files" in kwargs["description"]

    @pytest.mark.asyncio
    async def test_model_intent_leads_the_card(self, monkeypatch):
        manager = _patch_manager(monkeypatch, allowed_scopes=set())
        gated = self._gated(GovernanceMode.ASK)

        await gated.func(
            command="node build.js",
            intent="i will run the production build to check the bundle",
        )
        description = manager.request_approval.await_args.kwargs["description"]
        assert description.startswith(
            "The agent will run the production build to check the bundle."
        )
        assert description.endswith("It runs code, which could change files.")

    @pytest.mark.asyncio
    async def test_intent_does_not_change_the_classification(self, monkeypatch):
        manager = _patch_manager(monkeypatch, allowed_scopes=set())
        gated = self._gated(GovernanceMode.AUTO)
        command = "git push origin main"

        await gated.func(command=command)
        baseline = manager.request_approval.await_args.kwargs
        await gated.func(command=command, intent="read the git log")
        with_intent = manager.request_approval.await_args.kwargs

        assert with_intent["tier"] == baseline["tier"]
        assert with_intent["scopes"] == baseline["scopes"]

    @pytest.mark.asyncio
    async def test_intent_is_not_forwarded_to_the_tool(self, monkeypatch):
        _patch_manager(monkeypatch, allowed_scopes=set())
        gated = self._gated(GovernanceMode.ASK)

        assert (
            await gated.async_call(
                command="mkdir out", intent="create the output directory"
            )
            == "ran mkdir out"
        )


class TestIntentSchema:
    def test_malformed_schema_is_left_alone(self):
        schema = {"type": "function", "function": {"name": "x"}}
        assert _with_intent_argument(schema) == schema

    def test_schema_without_properties_is_left_alone(self):
        schema = {
            "type": "function",
            "function": {"parameters": {"type": "object"}},
        }
        assert _with_intent_argument(schema) == schema

    def test_non_dict_schema_is_left_alone(self):
        assert _with_intent_argument(None) is None


class TestIntentNormalization:
    def test_first_person_becomes_the_agent(self):
        assert _normalize_intent("i will run the tests") == (
            "The agent will run the tests."
        )

    def test_whitespace_and_missing_period(self):
        assert _normalize_intent("  Run   the tests\n") == (
            "The agent will run the tests."
        )

    def test_empty_and_non_string(self):
        assert _normalize_intent(None) == ""
        assert _normalize_intent("   ") == ""
        assert _normalize_intent(42) == ""

    def test_long_intent_is_capped(self):
        text = _normalize_intent("check " + "x" * 1000)
        assert len(text) <= 320
        assert text.endswith("...")


async def shell_exec(command: str) -> str:
    """Run a shell command.

    Args:
        command: The command line.
    """
    return f"ran {command}"


async def write_to_file(path: str, content: str) -> str:
    """Write a file.

    Args:
        path: Destination path.
        content: File body.
    """
    return f"wrote {path}: {content}"


async def shell_write_content_to_file(content: str, file_path: str) -> str:
    """Write content to a file through the terminal toolkit.

    Args:
        content: File body.
        file_path: Destination path.
    """
    return f"wrote {file_path}: {content}"


async def shell_write_to_process(id: str, command: str) -> str:
    """Send input to a running process.

    Args:
        id: Session id.
        command: Text to send to stdin.
    """
    return f"sent {command} to {id}"


async def edit_file(path: str, old_content: str, new_content: str) -> str:
    """Edit a file in place.

    Args:
        path: File path.
        old_content: Text to replace.
        new_content: Replacement text.
    """
    return f"edited {path}"


async def apply_patch(patch: str) -> str:
    """Apply a unified diff.

    Args:
        patch: The diff text.
    """
    return f"patched {patch}"


async def execute_code(code: str) -> str:
    """Run Python code.

    Args:
        code: The source snippet.
    """
    return f"executed {code}"


async def send_message_to_user(message: str) -> str:
    """Send a message.

    Args:
        message: The message body.
    """
    return f"sent {message}"


def _worker_tools() -> dict[str, FunctionTool]:
    tools = [
        FunctionTool(shell_exec),
        FunctionTool(shell_write_content_to_file),
        FunctionTool(shell_write_to_process),
        FunctionTool(write_to_file),
        FunctionTool(edit_file),
        FunctionTool(apply_patch),
        FunctionTool(execute_code),
        FunctionTool(send_message_to_user),
    ]
    return {tool.get_function_name(): tool for tool in tools}


def _worker_lock(monkeypatch, mode):
    """Point the gate's manager lookup and the session-mode lookup at one
    lock carrying `mode`."""
    manager = MagicMock()
    manager.request_approval = AsyncMock(return_value="approved")
    task_lock = MagicMock()
    task_lock.approval_manager = manager
    task_lock.governance_mode = mode
    task_lock.allowed_approval_scopes = lambda: {
        CommandScope.FILE_READS.value
    }
    monkeypatch.setattr(
        "app.agent.toolkit.governance_toolkit.get_task_lock",
        lambda project_id: task_lock,
    )
    monkeypatch.setattr(
        "app.agent.toolkit.governance_toolkit.get_task_lock_if_exists",
        lambda project_id: task_lock,
    )
    return manager


class TestTerminalWriteTools:
    """The terminal toolkit's non-shell tools must gate like `shell_exec`.

    `shell_write_content_to_file` and `shell_write_to_process` are separate
    FunctionTools. Gating only `shell_exec` let a file write through with no
    card in ASK mode.
    """

    def _gated(self, tool, mode):
        return wrap_with_approval(
            tool,
            field_name="terminal",
            agent_name="single_agent",
            api_task_id="project_1",
            mode=mode,
        )

    @pytest.mark.asyncio
    async def test_file_write_prompts_in_ask(self, monkeypatch):
        manager = _patch_manager(monkeypatch, allowed_scopes=set())
        gated = self._gated(
            FunctionTool(shell_write_content_to_file), GovernanceMode.ASK
        )

        await gated.func(content="hello\n", file_path="smoke.txt")
        manager.request_approval.assert_awaited_once()
        kwargs = manager.request_approval.await_args.kwargs
        assert kwargs["tier"] == int(CommandTier.WORKSPACE_WRITE)
        assert kwargs["scopes"] == [CommandScope.FILE_WRITES.value]

    @pytest.mark.asyncio
    async def test_file_write_skips_prompt_in_auto(self, monkeypatch):
        manager = _patch_manager(monkeypatch)
        gated = self._gated(
            FunctionTool(shell_write_content_to_file), GovernanceMode.AUTO
        )

        await gated.func(content="hello\n", file_path="smoke.txt")
        manager.request_approval.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_file_write_is_suppressed_by_file_writes_scope(
        self, monkeypatch
    ):
        manager = _patch_manager(
            monkeypatch,
            allowed_scopes={CommandScope.FILE_WRITES.value},
        )
        gated = self._gated(
            FunctionTool(shell_write_content_to_file), GovernanceMode.ASK
        )

        await gated.func(content="hello\n", file_path="smoke.txt")
        manager.request_approval.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_write_to_process_prompts_even_in_auto(self, monkeypatch):
        manager = _patch_manager(
            monkeypatch,
            allowed_scopes={scope.value for scope in CommandScope},
        )
        gated = self._gated(
            FunctionTool(shell_write_to_process), GovernanceMode.AUTO
        )

        await gated.func(id="session_1", command="rm -rf /")
        manager.request_approval.assert_awaited_once()
        kwargs = manager.request_approval.await_args.kwargs
        assert kwargs["tier"] == int(CommandTier.DESTRUCTIVE)
        assert kwargs["scopes"] == []


class TestWorkerParity:
    def test_mutating_tools_are_wrapped_and_reads_are_not(self):
        tools = _worker_tools()
        gated = gate_worker_tools(
            list(tools.values()),
            api_task_id="project_1",
            agent_name="developer_agent",
        )
        by_name = {tool.get_function_name(): tool for tool in gated}

        for name in (
            "shell_exec",
            "shell_write_content_to_file",
            "shell_write_to_process",
            "write_to_file",
            "edit_file",
            "apply_patch",
            "execute_code",
        ):
            assert by_name[name] is not tools[name]
            assert (
                _without_intent(by_name[name].openai_tool_schema)
                == tools[name].openai_tool_schema
            )
        assert (
            by_name["send_message_to_user"] is tools["send_message_to_user"]
        )

    def test_gating_preserves_order_and_count(self):
        tools = list(_worker_tools().values())
        gated = gate_worker_tools(
            tools, api_task_id="project_1", agent_name="browser_agent"
        )
        assert [t.get_function_name() for t in gated] == [
            t.get_function_name() for t in tools
        ]

    @pytest.mark.asyncio
    async def test_worker_shell_prompts_in_ask(self, monkeypatch):
        manager = _worker_lock(monkeypatch, "ask")
        tools = _worker_tools()
        gated = gate_worker_tools(
            list(tools.values()),
            api_task_id="project_1",
            agent_name="developer_agent",
        )
        shell = next(
            tool for tool in gated if tool.get_function_name() == "shell_exec"
        )

        assert await shell.func(command="mkdir out") == "ran mkdir out"
        manager.request_approval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_worker_shell_skips_prompt_in_auto(self, monkeypatch):
        manager = _worker_lock(monkeypatch, "auto")
        tools = _worker_tools()
        gated = gate_worker_tools(
            list(tools.values()),
            api_task_id="project_1",
            agent_name="developer_agent",
        )
        shell = next(
            tool for tool in gated if tool.get_function_name() == "shell_exec"
        )

        assert await shell.func(command="mkdir out") == "ran mkdir out"
        manager.request_approval.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_worker_code_execution_prompts_in_ask(self, monkeypatch):
        manager = _worker_lock(monkeypatch, "ask")
        tools = _worker_tools()
        gated = gate_worker_tools(
            list(tools.values()),
            api_task_id="project_1",
            agent_name="developer_agent",
        )
        code = next(
            tool
            for tool in gated
            if tool.get_function_name() == "execute_code"
        )

        await code.func(code="print(1)")
        manager.request_approval.assert_awaited_once()
        kwargs = manager.request_approval.await_args.kwargs
        assert kwargs["tier"] == int(CommandTier.WORKSPACE_WRITE)

    @pytest.mark.asyncio
    async def test_worker_destructive_command_prompts_even_in_auto(
        self, monkeypatch
    ):
        manager = _worker_lock(monkeypatch, "auto")
        tools = _worker_tools()
        gated = gate_worker_tools(
            list(tools.values()),
            api_task_id="project_1",
            agent_name="browser_agent",
        )
        shell = next(
            tool for tool in gated if tool.get_function_name() == "shell_exec"
        )

        await shell.func(command="git push origin main")
        manager.request_approval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unrecorded_mode_fails_closed_to_ask(self, monkeypatch):
        manager = _worker_lock(monkeypatch, None)
        tools = _worker_tools()
        gated = gate_worker_tools(
            list(tools.values()),
            api_task_id="project_1",
            agent_name="document_agent",
        )
        write = next(
            tool
            for tool in gated
            if tool.get_function_name() == "write_to_file"
        )

        await write.func(path="a.txt", content="x")
        manager.request_approval.assert_awaited_once()


class TestSessionMode:
    def test_records_coerced_mode(self, monkeypatch):
        task_lock = MagicMock()
        monkeypatch.setattr(
            "app.agent.toolkit.governance_toolkit.get_task_lock_if_exists",
            lambda project_id: task_lock,
        )

        record_session_governance_mode("project_1", "ask")
        assert task_lock.governance_mode == "ask"

        record_session_governance_mode("project_1", None)
        assert task_lock.governance_mode == "auto"

    def test_missing_lock_is_a_no_op(self, monkeypatch):
        monkeypatch.setattr(
            "app.agent.toolkit.governance_toolkit.get_task_lock_if_exists",
            lambda project_id: None,
        )
        record_session_governance_mode("project_1", "ask")
        assert session_governance_mode("project_1") is GovernanceMode.ASK

    def test_reads_the_recorded_mode(self, monkeypatch):
        task_lock = MagicMock()
        task_lock.governance_mode = "ask"
        monkeypatch.setattr(
            "app.agent.toolkit.governance_toolkit.get_task_lock_if_exists",
            lambda project_id: task_lock,
        )
        assert session_governance_mode("project_1") is GovernanceMode.ASK

        task_lock.governance_mode = "auto"
        assert session_governance_mode("project_1") is GovernanceMode.AUTO

    def test_toolkit_config_parsing(self):
        assert (
            mode_from_toolkit_config({"governance": {"mode": "ask"}})
            is GovernanceMode.ASK
        )
        assert (
            mode_from_toolkit_config({"governance": {"mode": "auto"}})
            is GovernanceMode.AUTO
        )
        assert mode_from_toolkit_config(None) is GovernanceMode.AUTO
        assert mode_from_toolkit_config({}) is GovernanceMode.AUTO
