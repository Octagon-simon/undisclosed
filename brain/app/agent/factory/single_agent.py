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

import asyncio
import logging
import platform
from dataclasses import dataclass
from typing import Literal

from camel.messages import BaseMessage

from app.agent.agent_model import agent_model
from app.agent.factory.toolkit_assembler import assemble_single_agent_toolkits
from app.agent.tool_rag import ToolRAGSelector, tool_rag_enabled
from app.agent.prompt import (
    SINGLE_AGENT_SYS_PROMPT,
    append_connected_app_mcp_notice,
)
from app.agent.utils import NOW_STR
from app.hands.interface import IHands
from app.model.chat import Chat
from app.component.environment import env
from app.service.task import Agents
from app.utils.file_utils import get_working_directory

logger = logging.getLogger("single_agent_factory")


def _max_iteration() -> int | None:
    """Optional cap on tool-call rounds per turn. DEFAULT: unbounded (0) — a low
    cap truncates legitimate long tasks and leaves a dangling non-answer, and the
    real "runs forever" case is handled by the deferred-follow-up fix, not this
    blunt cap. Set UNDISCLOSED_MAX_ITERATION=<N> to re-enable a safety cap."""
    raw = env("UNDISCLOSED_MAX_ITERATION", "0")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


@dataclass(frozen=True)
class AgentRuntimeConfig:
    role: Literal["root", "subagent"] = "root"
    depth: int = 0
    max_depth: int = 1

    @property
    def can_delegate(self) -> bool:
        return self.depth < self.max_depth


async def single_agent(
    options: Chat,
    *,
    task_id: str | None = None,
    hands: IHands | None = None,
    pause_event: asyncio.Event | None = None,
    runtime: AgentRuntimeConfig | None = None,
):
    """Create the root Single Agent using CAMEL-first tool assembly."""

    runtime = runtime or AgentRuntimeConfig()
    working_directory = get_working_directory(options)
    current_task_id = task_id or options.task_id

    assembly = await assemble_single_agent_toolkits(
        options,
        task_id=current_task_id,
        working_directory=working_directory,
        hands=hands,
        can_delegate=runtime.can_delegate,
        current_depth=runtime.depth,
        max_depth=runtime.max_depth,
    )

    system_message = SINGLE_AGENT_SYS_PROMPT.format(
        platform_system=platform.system(),
        platform_machine=platform.machine(),
        working_directory=working_directory,
        now_str=NOW_STR,
    )
    system_message = append_connected_app_mcp_notice(system_message)

    # Tool RAG: expose only a small core + the tools most relevant to the current
    # message, instead of re-sending every toolkit's + MCP's schema on every LLM
    # call. The selector is kept on the agent so each turn can re-select
    # (see single_agent_service.run_turn). Degrades to all tools on any failure.
    tool_rag_selector: ToolRAGSelector | None = None
    initial_tools = assembly.tools
    if tool_rag_enabled():
        try:
            tool_rag_selector = ToolRAGSelector(assembly.tools)
            if tool_rag_selector.total_tools:
                # Start LEAN — core only. The per-turn router/reconcile (see
                # single_agent_service.run_turn) attaches exactly what THIS
                # message needs before the first model call, so we never build
                # the agent with the whole catalog.
                initial_tools = tool_rag_selector.select_tools("")
                logger.info(
                    "Tool-RAG: agent starts with %d core tools (of %d); "
                    "per-turn router selects the rest",
                    len(initial_tools),
                    tool_rag_selector.total_tools,
                )
        except Exception:
            logger.warning(
                "Tool-RAG init failed; using all tools", exc_info=True
            )
            tool_rag_selector = None
            initial_tools = assembly.tools

    # Tell the agent which capabilities it can pull in mid-task with
    # `load_capability([...])`. This is the "agent decides when to attach a tool"
    # mechanism for needs that its opening message didn't imply (per-turn RAG
    # handles the rest). Best-effort; skipped if there's nothing loadable.
    # Deferred capabilities (e.g. the Browser/Screenshot toolkits) are NOT built
    # at assembly — they're constructed on demand so a reasoning turn never
    # launches Chromium. Surface them as loadable alongside the tool-RAG catalog.
    loadable_names: list[str] = list(assembly.deferred_capabilities.keys())
    if tool_rag_selector is not None:
        try:
            loadable_names.extend(tool_rag_selector.capability_catalog())
        except Exception:
            logger.warning("capability catalog build failed", exc_info=True)
    if loadable_names:
        system_message += (
            "\n\n<loadable_capabilities>\n"
            "These tool capabilities are NOT loaded by default. The moment a "
            "task needs one, call load_capability([...]) with the name(s) "
            "below, then use the tools it returns:\n"
            + "\n".join(f"- {name}" for name in loadable_names)
            + "\n</loadable_capabilities>"
        )

    agent = agent_model(
        Agents.single_agent,
        BaseMessage.make_assistant_message(
            role_name="Single Agent",
            content=system_message,
        ),
        options,
        initial_tools,
        tool_names=assembly.tool_names,
        toolkits_to_register_agent=assembly.toolkits_to_register_agent,
    )
    agent._tool_rag_selector = tool_rag_selector

    # The `load_capability` meta-tool: lets the agent attach a whole toolkit
    # on demand mid-task (CAMEL rebuilds tool schemas each iteration, so newly
    # added tools are usable on the next model call). Additive — per-turn RAG
    # still runs; this just covers mid-task needs.
    if tool_rag_selector is not None or assembly.deferred_capabilities:
        try:
            from camel.toolkits import FunctionTool

            _selector = tool_rag_selector
            _agent_ref = agent
            _deferred = assembly.deferred_capabilities

            async def load_capability(capabilities: list[str]) -> str:
                """Attach additional tool capabilities (toolkits) when the
                current task needs them and they are not already available.

                Args:
                    capabilities: Names of the capabilities to load, taken from
                        the <loadable_capabilities> list in your context
                        (e.g. ["Browser Toolkit"]).

                Returns:
                    A short status describing what was loaded.
                """
                loaded: list[str] = []
                # 1) Deferred toolkits are BUILT on demand here (e.g. the browser
                #    toolkit launches Chromium only at this point).
                rag_wanted: list[str] = []
                for cap in capabilities:
                    factory = _deferred.get(cap)
                    if factory is None:
                        rag_wanted.append(cap)
                        continue
                    try:
                        tools = await factory(_agent_ref)
                        if tools:
                            _agent_ref.add_tools(tools)
                            loaded.append(cap)
                    except Exception as exc:  # noqa: BLE001
                        return f"Failed to load {cap}: {exc}"
                # 2) Everything else comes from the tool-RAG catalog.
                if rag_wanted and _selector is not None:
                    try:
                        tools = _selector.tools_for_capabilities(
                            rag_wanted, options.question
                        )
                        if tools:
                            _agent_ref.add_tools(tools)
                            loaded.extend(rag_wanted)
                    except Exception as exc:  # noqa: BLE001
                        return f"Failed to load {rag_wanted}: {exc}"
                if loaded:
                    return (
                        f"Loaded {loaded}. Their tools are now available — call "
                        "them on your next step."
                    )
                available = ", ".join(
                    list(_deferred.keys())
                    + (
                        _selector.capability_catalog()
                        if _selector is not None
                        else []
                    )
                )
                return (
                    f"No capability matched {capabilities}. "
                    f"Available: {available}"
                )

            agent.add_tools([FunctionTool(load_capability)])
        except Exception:
            logger.warning(
                "load_capability meta-tool wiring failed", exc_info=True
            )
    # Bound the per-turn tool loop so an over-eager/looping agent can't run
    # forever (kept working after responding, forcing a manual Stop).
    try:
        agent.max_iteration = _max_iteration()
    except Exception:
        logger.warning("Failed to set max_iteration", exc_info=True)
    if pause_event is not None:
        agent.pause_event = pause_event
    if assembly.observable_todo_toolkit is not None:
        assembly.observable_todo_toolkit.agent_id = agent.agent_id
    agent._observable_todo_toolkit = assembly.observable_todo_toolkit

    if assembly.browser_toolkit is not None:
        agent._browser_toolkit = assembly.browser_toolkit
        agent._cdp_port = assembly.browser_port
        agent._cdp_url = assembly.browser_cdp_url
        agent._cdp_session_id = assembly.browser_session_id
        agent._cdp_task_id = options.task_id
        agent._cdp_options = options
        agent._cdp_owned_by_hands = assembly.browser_owned_by_hands

        def release_cdp_from_agent(agent_instance):
            port = getattr(agent_instance, "_cdp_port", None)
            session_id = getattr(agent_instance, "_cdp_session_id", None)
            if port is not None and session_id is not None:
                if options.cdp_browsers:
                    from app.agent.factory.browser import _cdp_pool_manager

                    _cdp_pool_manager.release_browser(port, session_id)
                elif hands is not None and getattr(
                    agent_instance, "_cdp_owned_by_hands", False
                ):
                    try:
                        hands.release_resource("browser", session_id)
                    except Exception:
                        pass

        agent._cdp_acquire_callback = None
        agent._cdp_release_callback = release_cdp_from_agent
    return agent
