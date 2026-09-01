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

from app.agent.toolkit.governance_toolkit import (
    DENIED_DECISIONS,
    GovernanceMode,
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
            field_name="terminal",
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
            field_name="terminal",
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
