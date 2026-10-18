# ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========
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
# ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========

"""Worker parity: every worker factory must gate its mutating tools.

The single agent asks before it runs a shell command or writes a file. The
workers build their own toolkits, so before this gate existed a browser or
developer worker could run what the single agent had to ask for.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

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


def _chat(sample_chat_data: dict) -> Chat:
    return Chat(
        **{
            **sample_chat_data,
            "model_platform": "aws-bedrock-converse",
            "model_type": "claude-opus-4-7",
            "api_key": "test_key",
            "api_url": "https://bedrock.local/v1",
            "installed_mcp": {"mcpServers": {}},
            "toolkit_config": None,
        }
    )


async def _build_worker(
    module_name, factory_name, options, tmp_path, monkeypatch
):
    module = importlib.import_module(module_name)
    captured: list[Any] = []

    def fake_agent_model(
        agent_name, system_message, options, tools, *args, **kwargs
    ):
        captured.extend(tools)
        agent = MagicMock()
        agent.agent_id = f"{agent_name}_id"
        agent.agent_name = agent_name
        return agent

    monkeypatch.setattr(module, "agent_model", fake_agent_model)
    monkeypatch.setattr(
        module, "get_working_directory", lambda opts: str(tmp_path)
    )
    if hasattr(module, "attach_load_capability"):
        monkeypatch.setattr(
            module, "attach_load_capability", lambda *a, **k: None
        )
    if module_name.endswith("document"):
        monkeypatch.setattr(
            module.GoogleDriveMCPToolkit,
            "get_can_use_tools",
            AsyncMock(return_value=[]),
        )
    if module_name.endswith("social_media"):
        monkeypatch.setattr(
            module.NotionMCPToolkit,
            "get_can_use_tools",
            AsyncMock(return_value=[]),
        )
        monkeypatch.setattr(
            module.GoogleGmailMCPToolkit,
            "get_can_use_tools",
            AsyncMock(return_value=[]),
        )

    factory = getattr(module, factory_name)
    result = (
        factory(options)
        if module_name.endswith("social_media")
        else factory(options, hands=None)
    )
    if inspect.isawaitable(result):
        await result
    return captured


def _by_name(tools):
    return {tool.get_function_name(): tool for tool in tools}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "factory_name"),
    [
        ("app.agent.factory.browser", "browser_agent"),
        ("app.agent.factory.developer", "developer_agent"),
        ("app.agent.factory.multi_modal", "multi_modal_agent"),
        ("app.agent.factory.document", "document_agent"),
        ("app.agent.factory.social_media", "social_media_agent"),
    ],
)
async def test_worker_shell_and_file_tools_are_gated(
    module_name, factory_name, sample_chat_data, monkeypatch, tmp_path
):
    options = _chat(sample_chat_data)
    _patch_side_effects(monkeypatch, tmp_path, options.project_id)

    tools = _by_name(
        await _build_worker(
            module_name, factory_name, options, tmp_path, monkeypatch
        )
    )

    assert tools["shell_exec"]._governance_field == "terminal"
    for name in ("shell_write_content_to_file", "shell_write_to_process"):
        if name in tools:
            assert tools[name]._governance_field == "terminal"
    for name in ("write_to_file", "edit_file", "notebook_edit_cell"):
        if name in tools:
            assert tools[name]._governance_field == "file_write"
