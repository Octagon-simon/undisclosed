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

"""Single-agent coverage tools: config gate and approval gate."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.agent.factory.toolkit_assembler import (
    assemble_single_agent_toolkits,
    toolkit_enabled,
)
from app.model.chat import Chat
from app.service.task import TaskLock, task_locks

pytestmark = pytest.mark.unit


class DummyTaskLock:
    def add_human_input_listen(self, agent_name: str) -> None:
        pass

    async def put_queue(self, data: Any) -> None:
        pass

    async def get_human_input(self, agent_name: str) -> str:
        return ""


def _patch_side_effects(monkeypatch, tmp_path, project_id):
    import app.agent.toolkit.human_toolkit as human_toolkit
    import app.agent.toolkit.terminal_toolkit as terminal_toolkit

    monkeypatch.setattr(
        human_toolkit, "get_task_lock", lambda api_task_id: DummyTaskLock()
    )
    monkeypatch.setattr(
        terminal_toolkit.TerminalToolkit,
        "_setup_cloned_environment",
        lambda self: None,
    )
    monkeypatch.setitem(
        task_locks, project_id, TaskLock(project_id, asyncio.Queue(), {})
    )
    monkeypatch.setenv("file_save_path", str(tmp_path))
    monkeypatch.setenv("browser_port", "9222")


def _chat(sample_chat_data: dict, toolkit_config: dict | None = None) -> Chat:
    return Chat(
        **{
            **sample_chat_data,
            "model_platform": "aws-bedrock-converse",
            "model_type": "claude-opus-4-7",
            "api_key": "test_key",
            "api_url": "https://bedrock.local/v1",
            "installed_mcp": {"mcpServers": {}},
            "toolkit_config": toolkit_config,
        }
    )


async def _assemble(options, tmp_path, monkeypatch):
    _patch_side_effects(monkeypatch, tmp_path, options.project_id)
    return await assemble_single_agent_toolkits(
        options,
        task_id=options.task_id,
        working_directory=str(tmp_path),
        hands=None,
        can_delegate=False,
    )


def _by_name(tools):
    return {
        tool.get_function_name(): tool
        for tool in tools
        if hasattr(tool, "get_function_name")
    }


def test_toolkit_enabled_defaults_on_and_honours_override(sample_chat_data):
    assert toolkit_enabled(_chat(sample_chat_data), "test_runner") is True
    disabled = _chat(sample_chat_data, {"test_runner": {"enabled": False}})
    assert toolkit_enabled(disabled, "test_runner") is False


@pytest.mark.asyncio
async def test_coverage_tools_are_gated(
    sample_chat_data, monkeypatch, tmp_path
):
    options = _chat(sample_chat_data)
    assembly = await _assemble(options, tmp_path, monkeypatch)
    tools = _by_name(assembly.tools)

    assert tools["run_tests"]._governance_field == "test_runner"
    assert tools["coverage_gap_plan"]._governance_field == "test_runner"


@pytest.mark.asyncio
async def test_disabling_test_runner_removes_the_tools(
    sample_chat_data, monkeypatch, tmp_path
):
    options = _chat(sample_chat_data, {"test_runner": {"enabled": False}})
    assembly = await _assemble(options, tmp_path, monkeypatch)
    names = set(_by_name(assembly.tools))

    assert "run_tests" not in names
    assert "coverage_gap_plan" not in names
