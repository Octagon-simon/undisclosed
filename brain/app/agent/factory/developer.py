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

import platform

from camel.messages import BaseMessage
from camel.toolkits import ToolkitMessageIntegration

from app.agent.agent_model import agent_model
from app.agent.factory.remote_sub_agent import (
    attach_remote_sub_agent_if_enabled,
)
from app.agent.listen_chat_agent import logger
from app.agent.prompt import (
    DEVELOPER_SYS_PROMPT,
    append_connected_app_mcp_notice,
)
from app.agent.tool_rag import attach_load_capability, prepare_tool_rag
from app.agent.toolkit.code_execution_toolkit import CodeExecutionToolkit
from app.agent.toolkit.diff_toolkit import DiffToolkit
from app.agent.toolkit.github_toolkit import GithubToolkit
from app.agent.toolkit.human_toolkit import HumanToolkit

# TODO: Remove NoteTakingToolkit and use TerminalToolkit instead
from app.agent.toolkit.note_taking_toolkit import NoteTakingToolkit
from app.agent.toolkit.screenshot_toolkit import ScreenshotToolkit
from app.agent.toolkit.search_toolkit import SearchToolkit
from app.agent.toolkit.skill_toolkit import SkillToolkit
from app.agent.toolkit.terminal_toolkit import TerminalToolkit
from app.agent.toolkit.test_runner_toolkit import TestRunnerToolkit
from app.agent.toolkit.web_deploy_toolkit import WebDeployToolkit
from app.agent.utils import NOW_STR
from app.hands.interface import IHands
from app.model.chat import Chat
from app.service.task import Agents
from app.utils.file_utils import get_working_directory


async def developer_agent(
    options: Chat,
    hands: IHands | None = None,
):
    working_directory = get_working_directory(options)
    logger.info(
        f"Creating developer agent for project: {options.project_id} "
        f"in directory: {working_directory}"
    )
    message_integration = ToolkitMessageIntegration(
        message_handler=HumanToolkit(
            options.project_id, Agents.developer_agent
        ).send_message_to_user
    )
    note_toolkit = NoteTakingToolkit(
        api_task_id=options.project_id,
        agent_name=Agents.developer_agent,
        working_directory=working_directory,
    )
    note_toolkit = message_integration.register_toolkits(note_toolkit)
    web_deploy_toolkit = WebDeployToolkit(api_task_id=options.project_id)
    web_deploy_toolkit = message_integration.register_toolkits(
        web_deploy_toolkit
    )
    screenshot_toolkit = ScreenshotToolkit(
        options.project_id,
        working_directory=working_directory,
        agent_name=Agents.developer_agent,
    )
    # Save reference before registering for toolkits_to_register_agent
    screenshot_toolkit_for_agent_registration = screenshot_toolkit
    screenshot_toolkit = message_integration.register_toolkits(
        screenshot_toolkit
    )
    skill_toolkit = SkillToolkit(
        options.project_id,
        Agents.developer_agent,
        working_directory=working_directory,
        user_id=options.skill_config_user_id(),
    )
    skill_toolkit = message_integration.register_toolkits(skill_toolkit)

    search_tools = SearchToolkit.get_can_use_tools(
        options.project_id, agent_name=Agents.developer_agent
    )
    if search_tools:
        search_tools = message_integration.register_functions(search_tools)
    else:
        search_tools = []

    # Specialized developer toolkits (diff/patch, test runner, code execution)
    # so the workforce developer worker is as equipped for real engineering as
    # the single agent — previously it only had terminal/notes/search.
    diff_toolkit = message_integration.register_toolkits(
        DiffToolkit(
            options.project_id,
            Agents.developer_agent,
            working_directory=working_directory,
        )
    )
    test_runner_toolkit = message_integration.register_toolkits(
        TestRunnerToolkit(
            options.project_id,
            Agents.developer_agent,
            working_directory=working_directory,
        )
    )
    code_execution_toolkit = message_integration.register_toolkits(
        CodeExecutionToolkit(options.project_id)
    )
    # GitHub tools are only available when a token is configured (returns [] if
    # not), so this stays a no-op for users without GITHUB_ACCESS_TOKEN.
    github_tools = GithubToolkit.get_can_use_tools(options.project_id)
    if github_tools:
        github_tools = message_integration.register_functions(github_tools)
    else:
        github_tools = []

    tools = [
        *HumanToolkit.get_can_use_tools(
            options.project_id, Agents.developer_agent
        ),
        *note_toolkit.get_tools(),
        *web_deploy_toolkit.get_tools(),
        *screenshot_toolkit.get_tools(),
        *skill_toolkit.get_tools(),
        *search_tools,
        *diff_toolkit.get_tools(),
        *test_runner_toolkit.get_tools(),
        *code_execution_toolkit.get_tools(),
        *github_tools,
    ]
    tool_names = [
        HumanToolkit.toolkit_name(),
        NoteTakingToolkit.toolkit_name(),
        WebDeployToolkit.toolkit_name(),
        ScreenshotToolkit.toolkit_name(),
        SkillToolkit.toolkit_name(),
        DiffToolkit.toolkit_name(),
        TestRunnerToolkit.toolkit_name(),
        CodeExecutionToolkit.toolkit_name(),
    ]
    if search_tools:
        tool_names.append(SearchToolkit.toolkit_name())
    if github_tools:
        tool_names.append(GithubToolkit.toolkit_name())
    if hands is None or hands.can_execute_terminal():
        terminal_toolkit = TerminalToolkit(
            options.project_id,
            Agents.developer_agent,
            working_directory=working_directory,
            safe_mode=True,
            clone_current_env=True,
        )
        terminal_toolkit = message_integration.register_toolkits(
            terminal_toolkit
        )
        tools.extend(terminal_toolkit.get_tools())
        tool_names.append(TerminalToolkit.toolkit_name())

    system_message = DEVELOPER_SYS_PROMPT.format(
        platform_system=platform.system(),
        platform_machine=platform.machine(),
        working_directory=working_directory,
        now_str=NOW_STR,
    )
    system_message = append_connected_app_mcp_notice(system_message)
    system_message = attach_remote_sub_agent_if_enabled(
        options=options,
        agent_name=Agents.developer_agent,
        working_directory=working_directory,
        tools=tools,
        tool_names=tool_names,
        system_message=system_message,
        local_tool_description="local `shell_exec` or local file writes",
        message_integration=message_integration,
    )

    # Tool-RAG: start the worker LEAN (core tools + a load_capability meta-tool)
    # instead of shipping every toolkit schema on each step. This is the same
    # token-saving mechanism the single agent uses. FAIL-SOFT: on any error it
    # returns the full tool set, so the worker is never worse off than before.
    initial_tools, system_message, tool_rag_selector = prepare_tool_rag(
        tools, system_message
    )

    agent = agent_model(
        Agents.developer_agent,
        BaseMessage.make_assistant_message(
            role_name="Developer Agent",
            content=system_message,
        ),
        options,
        initial_tools,
        tool_names=tool_names,
        toolkits_to_register_agent=[
            screenshot_toolkit_for_agent_registration,
        ],
    )
    attach_load_capability(agent, tool_rag_selector, options.question)
    return agent
