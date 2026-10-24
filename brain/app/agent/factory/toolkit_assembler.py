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

import asyncio
import logging
import os
import platform
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from camel.toolkits import (
    FunctionTool,
    MCPToolkit,
    PlanningWorktreeToolkit,
    RegisteredAgentToolkit,
    ToolkitMessageIntegration,
    WebFetchToolkit,
)

from app.agent.toolkit.app_capture_toolkit import AppCaptureToolkit
from app.agent.toolkit.code_query_toolkit import CodeQueryToolkit
from app.agent.toolkit.code_review_toolkit import CodeReviewToolkit
from app.agent.toolkit.code_search_toolkit import CodeSearchToolkit
from app.agent.toolkit.depth_limited_agent_toolkit import (
    DepthLimitedAgentToolkit,
)
from app.agent.toolkit.diff_toolkit import (
    WRITE_TOOL_NAMES as DIFF_WRITE_TOOL_NAMES,
    DiffToolkit,
)
from app.agent.toolkit.figma_toolkit import FigmaToolkit
from app.agent.toolkit.file_write_toolkit import FileToolkit
from app.agent.toolkit.git_toolkit import (
    WRITE_TOOL_NAMES as GIT_WRITE_TOOL_NAMES,
    GitToolkit,
)
from app.agent.toolkit.github_toolkit import (
    WRITE_TOOL_NAMES as GITHUB_WRITE_TOOL_NAMES,
    GithubToolkit,
)
from app.agent.toolkit.google_calendar_toolkit import GoogleCalendarToolkit
from app.agent.toolkit.governance_toolkit import (
    TEST_RUNNER_TOOL_NAMES,
    GovernanceMode,
    gate_tool_if_named,
    record_session_governance_mode,
)
from app.agent.toolkit.human_toolkit import HumanToolkit
from app.agent.toolkit.hybrid_browser_toolkit import HybridBrowserToolkit
from app.agent.toolkit.iris_toolkit import IrisToolkit
from app.agent.toolkit.lark_toolkit import LarkToolkit
from app.agent.toolkit.linkedin_toolkit import LinkedInToolkit
from app.agent.toolkit.memory_toolkit import MemoryToolkit
from app.agent.toolkit.mongodb_toolkit import (
    WRITE_TOOL_NAMES as MONGO_WRITE_TOOL_NAMES,
    MongoDBToolkit,
)
from app.agent.toolkit.observable_todo_toolkit import ObservableTodoToolkit
from app.agent.toolkit.project_context_toolkit import ProjectContextToolkit
from app.agent.toolkit.reddit_toolkit import RedditToolkit
from app.agent.toolkit.screenshot_toolkit import ScreenshotToolkit
from app.agent.toolkit.search_toolkit import SearchToolkit
from app.agent.toolkit.skill_toolkit import SkillToolkit
from app.agent.toolkit.slack_toolkit import SlackToolkit
from app.agent.toolkit.terminal_toolkit import TerminalToolkit
from app.agent.toolkit.test_runner_toolkit import TestRunnerToolkit
from app.agent.toolkit.twitter_toolkit import TwitterToolkit
from app.agent.toolkit.web_deploy_toolkit import WebDeployToolkit
from app.agent.toolkit.whatsapp_toolkit import WhatsAppToolkit
from app.component.environment import env
from app.hands.interface import IHands
from app.model.chat import Chat
from app.service.task import Agents
from app.utils.browser_launcher import normalize_cdp_url

logger = logging.getLogger("toolkit_assembler")

DEFAULT_SINGLE_AGENT_TOOLKIT_CONFIG: dict[str, Any] = {
    "human": {"enabled": True},
    "file": {"enabled": True},
    "web_deploy": {"enabled": True},
    # Image Reader: read_image for files on disk, plus a desktop capture tool
    # for "what is on my screen" tasks. Set enable_desktop_capture=False to
    # keep only read_image.
    "screenshot": {"enabled": True, "enable_desktop_capture": True},
    # Live web-page camera (bundled iris binary). Deferred by default: it costs
    # one line in <loadable_capabilities> until a task actually needs pixels.
    "page_screenshot": {"enabled": True},
    # Running-app camera: macOS app windows, booted iOS Simulators, Android
    # devices. Off the tool list until a task asks for it (same deferral as the
    # page camera), and advertised only when a backend exists on this host.
    "app_screenshot": {"enabled": True},
    "skill": {"enabled": True},
    "todo": {"enabled": True},
    "memory": {"enabled": True},
    "project_context": {"enabled": True},
    "code_query": {"enabled": True},
    "code_search": {"enabled": True},
    "search": {"enabled": True},
    # Third-party connectors (Slack, Lark, X/Twitter, WhatsApp, LinkedIn,
    # Reddit, Google Calendar). Each toolkit is a no-op unless its token is
    # configured, so this only surfaces the apps the user actually connected.
    # Without it a SINGLE-AGENT turn (including a trigger execution) saw the
    # file/terminal/MCP tools but never the Slack toolkit -- the agent then
    # complained "I need Slack tools" and fell back to raw curl.
    "connectors": {"enabled": True},
    "browser": {"enabled": True},
    "terminal": {"enabled": True},
    # Deterministic code review (run_checks + review_diff). Read-only, no
    # external token; pairs with the typecheck/verification flow.
    "code_review": {"enabled": True},
    "web_fetch": {"enabled": True},
    "planning_worktree": {"enabled": True},
    "mcp": {"enabled": True},
    "agent": {"enabled": True},
    # Governance gate: controls whether risky tools (terminal, file_write)
    # require explicit human approval. Default AUTO = no gating (ship dark).
    "governance": {"enabled": True, "mode": "auto"},
}

# Communication/social "connectors" for the SINGLE agent. Matches the built-in
# integrations advertised by the Connectors UI (chat_platform_controller's
# `_config_info_map`). Each entry is (label, toolkit class); the toolkit's
# `get_can_use_tools` returns [] unless its env token is set, so only connected
# apps contribute tools. Figma / GitHub / MongoDB already have their own blocks
# below, so they are deliberately left out here.
_CONNECTOR_TOOLKITS: tuple[tuple[str, Any], ...] = (
    ("slack_toolkit", SlackToolkit),
    ("lark_toolkit", LarkToolkit),
    ("twitter_toolkit", TwitterToolkit),
    ("whatsapp_toolkit", WhatsAppToolkit),
    ("linkedin_toolkit", LinkedInToolkit),
    ("reddit_toolkit", RedditToolkit),
    ("google_calendar_toolkit", GoogleCalendarToolkit),
)


@dataclass
class ToolkitAssembly:
    tools: list[FunctionTool | Callable] = field(default_factory=list)
    tool_names: list[str] = field(default_factory=list)
    toolkits_to_register_agent: list[RegisteredAgentToolkit] = field(
        default_factory=list
    )
    observable_todo_toolkit: ObservableTodoToolkit | None = None
    browser_toolkit: HybridBrowserToolkit | None = None
    browser_port: int | None = None
    browser_cdp_url: str | None = None
    browser_session_id: str | None = None
    browser_owned_by_hands: bool = False
    # Capabilities NOT built at assembly time — the agent constructs them on
    # demand via load_capability (e.g. the Browser Toolkit, so a pure reasoning
    # turn never launches Chromium). Maps a capability name to an async factory
    # `async def(agent) -> list[FunctionTool]` that builds + registers it.
    deferred_capabilities: dict[str, Any] = field(default_factory=dict)

    def add_tools(
        self,
        tools: list[FunctionTool | Callable],
        toolkit_name: str,
    ) -> None:
        if not tools:
            return
        _tag_tools(tools, toolkit_name)
        self.tools.extend(tools)
        if toolkit_name not in self.tool_names:
            self.tool_names.append(toolkit_name)


def _merged_config(options: Chat) -> dict[str, Any]:
    config = {
        key: dict(value) if isinstance(value, dict) else value
        for key, value in DEFAULT_SINGLE_AGENT_TOOLKIT_CONFIG.items()
    }
    for key, value in (options.toolkit_config or {}).items():
        config[key] = value
    return config


def _enabled(config: dict[str, Any], name: str, default: bool = True) -> bool:
    value = config.get(name)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return bool(value.get("enabled", default))
    return bool(value)


def toolkit_enabled(options: Chat, name: str, default: bool = True) -> bool:
    """Whether `name` is enabled in this session's merged toolkit config.

    Workers build their own toolkits, so they read the same config as the
    single agent instead of ignoring a toolkit the user turned off.
    """
    return _enabled(_merged_config(options), name, default)


def _options(config: dict[str, Any], name: str) -> dict[str, Any]:
    value = config.get(name)
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if key != "enabled"}


def _governance_mode(config: dict[str, Any]) -> GovernanceMode:
    """Resolve the effective governance mode from the merged config."""
    value = _options(config, "governance")
    mode = value.get("mode") if isinstance(value, dict) else None
    return GovernanceMode.coerce(mode)


def _tag_tools(
    tools: list[FunctionTool | Callable], toolkit_name: str
) -> None:
    for tool in tools:
        try:
            tool._toolkit_name = toolkit_name
        except Exception:
            pass


def _get_browser_port(browser: dict) -> int:
    raw_port = browser.get("port")
    if raw_port is not None:
        return int(raw_port)

    raw_endpoint = browser.get("endpoint") or browser.get("cdp_url")
    if raw_endpoint:
        _, _, port = normalize_cdp_url(str(raw_endpoint))
        return port

    return int(env("browser_port", "9222"))


def _get_browser_endpoint(browser: dict) -> str:
    raw_endpoint = browser.get("endpoint") or browser.get("cdp_url")
    if raw_endpoint:
        endpoint, _, _ = normalize_cdp_url(str(raw_endpoint))
        return endpoint

    return f"http://localhost:{_get_browser_port(browser)}"


def _browser_enabled_tools() -> list[str]:
    return [
        "browser_click",
        "browser_type",
        "browser_back",
        "browser_forward",
        "browser_select",
        "browser_console_exec",
        "browser_console_view",
        "browser_switch_tab",
        "browser_enter",
        "browser_visit_page",
        "browser_scroll",
        "browser_sheet_read",
        "browser_sheet_input",
        "browser_get_page_snapshot",
        "browser_open",
        "browser_upload_file",
        "browser_download_file",
    ]


def _lazy_single_agent_extras() -> bool:
    """Whether to DEFER the Browser + Screenshot toolkits for the single agent —
    i.e. not build/register them at assembly (so a pure reasoning turn never
    launches Chromium), exposing them via load_capability instead.

    Requires tool-RAG (which provides the load_capability meta-tool the agent
    uses to pull them in). Disable with UNDISCLOSED_SINGLE_AGENT_LAZY_BROWSER=0.
    """
    try:
        from app.agent.tool_rag import tool_rag_enabled

        if not tool_rag_enabled():
            return False
    except Exception:
        return False
    raw = (env("UNDISCLOSED_SINGLE_AGENT_LAZY_BROWSER", "1") or "").strip().lower()
    return raw not in {"0", "false", "no"}


def _register_lazy_toolkit(agent: Any, toolkit: Any) -> None:
    """Bind a lazily-built RegisteredAgentToolkit to an already-created agent,
    mirroring what CAMEL does with toolkits_to_register_agent at construction
    (it calls `toolkit.register_agent(self)`)."""
    try:
        register = getattr(toolkit, "register_agent", None)
        if callable(register):
            register(agent)
    except Exception:
        logger.warning("lazy toolkit register_agent failed", exc_info=True)


async def _build_single_agent_screenshot(
    options, config, working_directory, message_integration, assembly, agent
):
    """Build + register the ScreenshotToolkit. Eager when agent is None (added
    to toolkits_to_register_agent), lazy otherwise (bound to the live agent)."""
    screenshot_options = {
        "working_directory": working_directory,
        "agent_name": Agents.single_agent,
        **_options(config, "screenshot"),
    }
    toolkit = ScreenshotToolkit(options.project_id, **screenshot_options)
    registered = message_integration.register_toolkits(toolkit)
    tools = registered.get_tools()
    _tag_tools(tools, ScreenshotToolkit.toolkit_name())
    if agent is None:
        assembly.toolkits_to_register_agent.append(toolkit)
        assembly.add_tools(tools, ScreenshotToolkit.toolkit_name())
    else:
        _register_lazy_toolkit(agent, toolkit)
    return tools


async def _build_single_agent_iris(
    options, config, working_directory, message_integration, assembly, agent
):
    """Build + register the Iris page camera. No browser launches at build time,
    so this is cheap either way; deferral only saves tool-schema tokens."""
    toolkit = IrisToolkit(
        options.project_id,
        Agents.single_agent,
        working_directory=working_directory,
        model_type=getattr(options, "model_type", None),
        model_platform=getattr(options, "model_platform", None),
        **_options(config, "page_screenshot"),
    )
    registered = message_integration.register_toolkits(toolkit)
    tools = registered.get_tools()
    _tag_tools(tools, IrisToolkit.toolkit_name())
    if agent is None:
        assembly.toolkits_to_register_agent.append(toolkit)
        assembly.add_tools(tools, IrisToolkit.toolkit_name())
    else:
        _register_lazy_toolkit(agent, toolkit)
    return tools


async def _build_single_agent_app_capture(
    options, config, working_directory, message_integration, assembly, agent
):
    """Build + register the running-app camera. Nothing is captured at build
    time, so this only costs the tool schemas once the model loads it."""
    toolkit = AppCaptureToolkit(
        options.project_id,
        Agents.single_agent,
        working_directory=working_directory,
        model_type=getattr(options, "model_type", None),
        model_platform=getattr(options, "model_platform", None),
        **_options(config, "app_screenshot"),
    )
    registered = message_integration.register_toolkits(toolkit)
    tools = registered.get_tools()
    _tag_tools(tools, AppCaptureToolkit.toolkit_name())
    if agent is None:
        assembly.toolkits_to_register_agent.append(toolkit)
        assembly.add_tools(tools, AppCaptureToolkit.toolkit_name())
    else:
        _register_lazy_toolkit(agent, toolkit)
    return tools


async def _build_single_agent_browser(
    options, config, hands, message_integration, assembly, agent
):
    """Build + register the HybridBrowserToolkit, LAUNCHING the CDP browser as a
    side effect. Eager when agent is None; lazy (from load_capability) otherwise.
    This is the expensive path we defer so reasoning turns don't spawn Chromium.
    """
    toolkit_session_id = str(uuid.uuid4())[:8]
    selected_port: int | None = None
    cdp_url: str | None = None
    cdp_owned_by_hands = False

    if options.cdp_browsers:
        from app.agent.factory.browser import _cdp_pool_manager

        selected_browser = _cdp_pool_manager.acquire_browser(
            options.cdp_browsers,
            toolkit_session_id,
            options.task_id,
            getattr(options, "project_id", None),
        )
        if selected_browser is None:
            selected_browser = options.cdp_browsers[0]
            logger.warning(
                "No available CDP browser in pool for Single Agent; "
                "using first browser",
                extra={
                    "project_id": options.project_id,
                    "task_id": options.task_id,
                },
            )
        selected_port = _get_browser_port(selected_browser)
        cdp_url = _get_browser_endpoint(selected_browser)
    else:
        existing_cdp_url = env("UNDISCLOSED_CDP_URL", "").strip()
        selected_port = int(env("browser_port", "9222"))
        cdp_url = f"http://localhost:{selected_port}"
        if existing_cdp_url:
            cdp_url = existing_cdp_url
            try:
                parsed = urlparse(existing_cdp_url)
                if parsed.port is not None:
                    selected_port = parsed.port
            except Exception:
                selected_port = int(env("browser_port", "9222"))
        else:
            acquired = False
            if hands is not None:
                try:
                    cdp_url = hands.acquire_resource(
                        "browser", toolkit_session_id, port=selected_port
                    )
                    cdp_owned_by_hands = True
                    acquired = True
                except (NotImplementedError, ValueError):
                    acquired = False
            if not acquired and options.keep_browser_warm:
                # Keep-warm only. Otherwise the toolkit launches on its first
                # browser action, so a reasoning-only turn spawns nothing.
                from app.utils.browser_launcher import (
                    ensure_cdp_browser_endpoint,
                )

                launched = ensure_cdp_browser_endpoint(selected_port)
                if launched:
                    cdp_url = launched
                    try:
                        parsed_port = urlparse(launched).port
                        if parsed_port:
                            selected_port = parsed_port
                    except Exception:
                        pass

    cdp_keep_current = bool(options.cdp_browsers)
    default_start_url = None if cdp_keep_current else "about:blank"
    browser_options = {
        "cdp_keep_current_page": cdp_keep_current,
        "default_start_url": default_start_url,
        "headless": False,
        "browser_log_to_file": True,
        "stealth": True,
        "session_id": toolkit_session_id,
        "cdp_url": cdp_url,
        "enabled_tools": _browser_enabled_tools(),
        **_options(config, "browser"),
    }
    toolkit = HybridBrowserToolkit(options.project_id, **browser_options)
    toolkit.agent_name = Agents.single_agent
    assembly.browser_toolkit = toolkit
    assembly.browser_port = selected_port
    assembly.browser_cdp_url = cdp_url
    assembly.browser_session_id = toolkit_session_id
    assembly.browser_owned_by_hands = cdp_owned_by_hands
    registered = message_integration.register_toolkits(toolkit)
    tools = registered.get_tools()
    _tag_tools(tools, HybridBrowserToolkit.toolkit_name())
    if agent is None:
        assembly.toolkits_to_register_agent.append(toolkit)
        assembly.add_tools(tools, HybridBrowserToolkit.toolkit_name())
    else:
        _register_lazy_toolkit(agent, toolkit)
    return tools


def _mcp_config(options: Chat, hands: IHands | None) -> dict[str, Any] | None:
    servers = dict((options.installed_mcp or {}).get("mcpServers", {}))
    # Also include MCP servers the user installed locally (~/.undisclosed/mcp.json,
    # written by /mcp/install — e.g. the embed's "Manage connectors" screen).
    # The request's installed_mcp only carries the cloud Connector Gateway, so
    # without this a locally-added MCP never reaches the agent. Request-provided
    # servers win on a name clash.
    try:
        from app.service.mcp_config import read_mcp_config

        local_servers = (read_mcp_config() or {}).get("mcpServers", {})
        for name, cfg in local_servers.items():
            servers.setdefault(name, cfg)
    except Exception:
        logger.warning("Failed to merge local MCP config", exc_info=True)
    if not servers:
        return None

    if hands is not None:
        servers = {
            name: cfg
            for name, cfg in servers.items()
            if hands.can_use_mcp(name)
        }
        if not servers:
            logger.info("Skipping MCPToolkit: no MCP servers allowed")
            return None

    normalized_servers = {}
    for name, cfg in servers.items():
        server_cfg = dict(cfg)
        server_env = dict(server_cfg.get("env", {}))
        server_env.setdefault(
            "MCP_REMOTE_CONFIG_DIR",
            env("MCP_REMOTE_CONFIG_DIR", os.path.expanduser("~/.mcp-auth")),
        )
        server_cfg["env"] = server_env
        normalized_servers[name] = server_cfg

    return {"mcpServers": normalized_servers}


async def assemble_single_agent_toolkits(
    options: Chat,
    *,
    task_id: str,
    working_directory: str,
    hands: IHands | None,
    can_delegate: bool,
    current_depth: int = 0,
    max_depth: int = 1,
) -> ToolkitAssembly:
    config = _merged_config(options)
    assembly = ToolkitAssembly()
    # Resolve governance once; ASK mode gates risky tools below.
    governance_mode = _governance_mode(config)
    # Publish the policy on the task lock: workers and triggers build their
    # own toolkits and must gate with the same mode.
    record_session_governance_mode(options.project_id, governance_mode)
    if governance_mode is GovernanceMode.ASK:
        logger.info(
            "Governance: ASK mode enabled - risky tools will require "
            "explicit human approval",
            extra={"project_id": options.project_id},
        )

    human_toolkit = HumanToolkit(options.project_id, Agents.single_agent)
    message_integration = ToolkitMessageIntegration(
        message_handler=human_toolkit.send_message_to_user
    )

    if _enabled(config, "human"):
        assembly.add_tools(
            human_toolkit.get_tools(), HumanToolkit.toolkit_name()
        )

    if _enabled(config, "file"):
        file_options = {
            "working_directory": working_directory,
            **_options(config, "file"),
        }
        toolkit = FileToolkit(
            options.project_id,
            **file_options,
        )
        toolkit.agent_name = Agents.single_agent
        toolkit = message_integration.register_toolkits(toolkit)
        file_tools = toolkit.get_tools()
        if governance_mode is GovernanceMode.ASK:
            file_tools = gate_tool_if_named(
                file_tools,
                target_names={
                    "write_to_file",
                    "edit_file",
                    "notebook_edit_cell",
                    "delete_files",
                    "restore_backup",
                },
                field_name="file_write",
                agent_name=Agents.single_agent,
                api_task_id=options.project_id,
            )
        assembly.add_tools(file_tools, FileToolkit.toolkit_name())

    if _enabled(config, "web_deploy"):
        toolkit = WebDeployToolkit(
            api_task_id=options.project_id,
            **_options(config, "web_deploy"),
        )
        toolkit.agent_name = Agents.single_agent
        toolkit = message_integration.register_toolkits(toolkit)
        assembly.add_tools(
            toolkit.get_tools(), WebDeployToolkit.toolkit_name()
        )

    if _enabled(config, "screenshot"):
        if _lazy_single_agent_extras():
            assembly.deferred_capabilities[
                ScreenshotToolkit.toolkit_name()
            ] = lambda agent: _build_single_agent_screenshot(
                options, config, working_directory, message_integration,
                assembly, agent,
            )
        else:
            await _build_single_agent_screenshot(
                options, config, working_directory, message_integration,
                assembly, None,
            )

    # Only advertise the page camera when the binary actually exists: a missing
    # iris (e.g. Windows) would otherwise cost the model a load_capability call
    # that can only return an error.
    if _enabled(config, "page_screenshot"):
        if IrisToolkit.resolve_binary():
            if _lazy_single_agent_extras():
                assembly.deferred_capabilities[
                    IrisToolkit.toolkit_name()
                ] = lambda agent: _build_single_agent_iris(
                    options, config, working_directory, message_integration,
                    assembly, agent,
                )
            else:
                await _build_single_agent_iris(
                    options, config, working_directory, message_integration,
                    assembly, None,
                )
        elif platform.system() != "Windows":
            # Windows has no iris release, so silence there. Everywhere else a
            # missing binary means a fresh clone skipped the fetch step.
            logger.warning(
                "Page Screenshots is enabled but the iris binary is missing "
                "for %s-%s; run `npm run fetch:iris` and restart the brain.",
                platform.system().lower(),
                platform.machine().lower(),
            )

    # Same rule as the page camera: only advertise a capability that can
    # actually produce a file here. Android-only hosts (Windows, Linux with
    # adb) still qualify; a host with no backend at all does not.
    if _enabled(config, "app_screenshot"):
        if AppCaptureToolkit.available_backends():
            if _lazy_single_agent_extras():
                assembly.deferred_capabilities[
                    AppCaptureToolkit.toolkit_name()
                ] = lambda agent: _build_single_agent_app_capture(
                    options, config, working_directory, message_integration,
                    assembly, agent,
                )
            else:
                await _build_single_agent_app_capture(
                    options, config, working_directory, message_integration,
                    assembly, None,
                )
        else:
            logger.info(
                "App Screenshots disabled: no window, simulator or Android "
                "backend available on this host."
            )

    if _enabled(config, "skill"):
        skill_options = {
            "working_directory": working_directory,
            "user_id": options.skill_config_user_id(),
            **_options(config, "skill"),
        }
        toolkit = SkillToolkit(
            options.project_id,
            Agents.single_agent,
            **skill_options,
        )
        toolkit = message_integration.register_toolkits(toolkit)
        assembly.add_tools(toolkit.get_tools(), SkillToolkit.toolkit_name())

    if _enabled(config, "todo"):
        # Scope the todo files (CAMEL persists todo.md / .todo.json in
        # working_dir and RELOADS them on init) PER PROJECT — not in the shared
        # workspace folder. Otherwise every new conversation in the same folder
        # reloads the previous project's plan (the "plan leaks into a new
        # conversation" bug). Store under the eigent data dir so it also stays
        # out of the user's repo.
        todo_scope = str(options.project_id or task_id)
        todo_dir = os.path.join(
            os.path.expanduser("~"), ".undisclosed", "todos", todo_scope
        )
        todo_options = {
            **_options(config, "todo"),
            "working_dir": todo_dir,
        }
        todo_toolkit = ObservableTodoToolkit(
            api_task_id=options.project_id,
            task_id=task_id,
            **todo_options,
        )
        todo_toolkit.agent_name = Agents.single_agent
        assembly.observable_todo_toolkit = todo_toolkit
        assembly.add_tools(
            todo_toolkit.get_tools(), ObservableTodoToolkit.toolkit_name()
        )

    if _enabled(config, "memory"):
        # Semantic memory: let the agent save/recall durable facts across
        # conversations (scoped to this user + project). Fail-soft internally.
        try:
            from app.memory.paths import canonical_user_id

            memory_user_key = canonical_user_id(
                options.user_id, email=options.email
            )
        except Exception:  # noqa: BLE001
            memory_user_key = None
        memory_toolkit = MemoryToolkit(
            api_task_id=options.project_id,
            user_key=memory_user_key,
            #same resolution as RunContext: a request may omit space_id
            space_id=options.space_id or options.project_id,
        )
        assembly.add_tools(
            memory_toolkit.get_tools(), MemoryToolkit.toolkit_name()
        )

    if _enabled(config, "project_context"):
        # repomix-backed project digest so the agent understands the codebase in
        # one call instead of many grep/file searches (cached per project).
        project_context_toolkit = ProjectContextToolkit(
            api_task_id=options.project_id,
            working_directory=working_directory,
        )
        assembly.add_tools(
            project_context_toolkit.get_tools(),
            ProjectContextToolkit.toolkit_name(),
        )

    if _enabled(config, "code_query"):
        # tree-sitter-backed precise code lookups (definitions, references,
        # imports, context) — the surgical companion to the repomix digest.
        code_query_toolkit = CodeQueryToolkit(
            api_task_id=options.project_id,
            working_directory=working_directory,
        )
        assembly.add_tools(
            code_query_toolkit.get_tools(),
            CodeQueryToolkit.toolkit_name(),
        )

    if _enabled(config, "code_search"):
        # Capped ripgrep-backed text search + directory listing so the agent
        # finds code in one targeted call instead of spraying shell_exec greps.
        code_search_toolkit = CodeSearchToolkit(
            api_task_id=options.project_id,
            working_directory=working_directory,
        )
        assembly.add_tools(
            code_search_toolkit.get_tools(),
            CodeSearchToolkit.toolkit_name(),
        )

    if _enabled(config, "search"):
        search_tools = SearchToolkit.get_can_use_tools(
            options.project_id, agent_name=Agents.single_agent
        )
        if search_tools:
            search_tools = message_integration.register_functions(search_tools)
            assembly.add_tools(search_tools, SearchToolkit.toolkit_name())

    # Figma: read components/nodes via the REST API. No-op unless a
    # FIGMA_ACCESS_TOKEN is configured (get_can_use_tools returns []).
    figma_tools = FigmaToolkit.get_can_use_tools(options.project_id)
    if figma_tools:
        figma_tools = message_integration.register_functions(figma_tools)
        assembly.add_tools(figma_tools, FigmaToolkit.toolkit_name())

    # GitHub: REST API tools (issues + pull requests). No-op unless a
    # GITHUB_ACCESS_TOKEN is configured (get_can_use_tools returns []), so the
    # single agent stays GitHub-free until a token is set. Mutating tools are
    # gated under Ask mode, mirroring the local git toolkit.
    github_tools = GithubToolkit.get_can_use_tools(options.project_id)
    if github_tools:
        github_tools = message_integration.register_functions(github_tools)
        # Wrapped in AUTO too: these writes are tier 2, so approval is
        # independent of the flag.
        github_tools = gate_tool_if_named(
            github_tools,
            target_names=GITHUB_WRITE_TOOL_NAMES,
            field_name="github_write",
            agent_name=Agents.single_agent,
            api_task_id=options.project_id,
            mode=governance_mode,
        )
        assembly.add_tools(github_tools, GithubToolkit.toolkit_name())

    # MongoDB: read-only ad-hoc queries (find/count/distinct/aggregate) over
    # mongosh. No-op unless a connection string is configured (MONGO_URL et al;
    # get_can_use_tools returns []). The free-form escape hatch (mongo_eval) is
    # the only mutating-capable tool, so it is gated under Ask mode.
    mongo_tools = MongoDBToolkit.get_can_use_tools(options.project_id)
    if mongo_tools:
        mongo_tools = message_integration.register_functions(mongo_tools)
        if governance_mode is GovernanceMode.ASK:
            mongo_tools = gate_tool_if_named(
                mongo_tools,
                target_names=MONGO_WRITE_TOOL_NAMES,
                field_name="mongo_write",
                agent_name=Agents.single_agent,
                api_task_id=options.project_id,
            )
        assembly.add_tools(mongo_tools, MongoDBToolkit.toolkit_name())

    # Connectors: the communication/social apps the user has connected (Slack,
    # Lark, X/Twitter, WhatsApp, LinkedIn, Reddit, Google Calendar). Each
    # get_can_use_tools is a no-op unless its token is set, so an unconnected
    # app contributes nothing. This is what gives a single-agent turn -- and
    # therefore a trigger execution -- the Slack tools it previously lacked.
    if _enabled(config, "connectors"):
        for _name, _toolkit_cls in _CONNECTOR_TOOLKITS:
            try:
                produced = _toolkit_cls.get_can_use_tools(options.project_id)
                connector_tools = (
                    await produced
                    if asyncio.iscoroutine(produced)
                    else produced
                )
                if connector_tools:
                    connector_tools = message_integration.register_functions(
                        list(connector_tools)
                    )
                    assembly.add_tools(
                        connector_tools, _toolkit_cls.toolkit_name()
                    )
                    logger.info(
                        "Connectors: attached %s (%d tools)",
                        _toolkit_cls.toolkit_name(),
                        len(connector_tools),
                    )
            except Exception:
                logger.warning(
                    "Connectors: failed to build %s; skipping",
                    _name,
                    exc_info=True,
                )

    if _enabled(config, "browser") and (
        hands is None or hands.can_use_browser()
    ):
        if _lazy_single_agent_extras():
            # Deferred: don't launch Chromium now. The agent load_capability()s
            # the "Browser Toolkit" only when a task actually needs the web.
            assembly.deferred_capabilities[
                HybridBrowserToolkit.toolkit_name()
            ] = lambda agent: _build_single_agent_browser(
                options, config, hands, message_integration, assembly, agent,
            )
        else:
            await _build_single_agent_browser(
                options, config, hands, message_integration, assembly, None,
            )

    if _enabled(config, "terminal") and (
        hands is None or hands.can_execute_terminal()
    ):
        terminal_options = {
            "working_directory": working_directory,
            "safe_mode": True,
            "clone_current_env": True,
            **_options(config, "terminal"),
        }
        toolkit = TerminalToolkit(
            options.project_id,
            Agents.single_agent,
            **terminal_options,
        )
        toolkit = message_integration.register_toolkits(toolkit)
        terminal_tools = toolkit.get_tools()
        # Wrapped in AUTO too: tier 2 must prompt even with the flag off.
        terminal_tools = gate_tool_if_named(
            terminal_tools,
            target_names={
                "shell_exec",
                "shell_write_content_to_file",
                "shell_write_to_process",
            },
            field_name="terminal",
            agent_name=Agents.single_agent,
            api_task_id=options.project_id,
            mode=governance_mode,
        )
        assembly.add_tools(terminal_tools, TerminalToolkit.toolkit_name())

    if _enabled(config, "git"):
        toolkit = GitToolkit(
            options.project_id,
            Agents.single_agent,
            working_directory=working_directory,
            **_options(config, "git"),
        )
        toolkit = message_integration.register_toolkits(toolkit)
        git_tools = toolkit.get_tools()
        # Wrapped in AUTO too: `git_push` is tier 2, so it prompts in every
        # mode. `git add`/`commit` stay tier 1 and only prompt in ASK.
        git_tools = gate_tool_if_named(
            git_tools,
            target_names=GIT_WRITE_TOOL_NAMES,
            field_name="git_write",
            agent_name=Agents.single_agent,
            api_task_id=options.project_id,
            mode=governance_mode,
        )
        assembly.add_tools(git_tools, GitToolkit.toolkit_name())

    if _enabled(config, "test_runner"):
        toolkit = TestRunnerToolkit(
            options.project_id,
            Agents.single_agent,
            working_directory=working_directory,
            **_options(config, "test_runner"),
        )
        toolkit = message_integration.register_toolkits(toolkit)
        # Both tools shell out to the project's coverage command, so they get
        # the `shell_exec` treatment: blocked commands are refused in every
        # mode, destructive ones always prompt, and ASK gates the rest.
        test_tools = gate_tool_if_named(
            toolkit.get_tools(),
            target_names=TEST_RUNNER_TOOL_NAMES,
            field_name="test_runner",
            agent_name=Agents.single_agent,
            api_task_id=options.project_id,
            mode=governance_mode,
        )
        assembly.add_tools(test_tools, TestRunnerToolkit.toolkit_name())

    if _enabled(config, "code_review"):
        toolkit = CodeReviewToolkit(
            options.project_id,
            Agents.single_agent,
            working_directory=working_directory,
            **_options(config, "code_review"),
        )
        toolkit = message_integration.register_toolkits(toolkit)
        # Deterministic + read-only: no Ask-mode gate needed.
        assembly.add_tools(
            toolkit.get_tools(), CodeReviewToolkit.toolkit_name()
        )

    if _enabled(config, "diff"):
        toolkit = DiffToolkit(
            options.project_id,
            Agents.single_agent,
            working_directory=working_directory,
            **_options(config, "diff"),
        )
        toolkit = message_integration.register_toolkits(toolkit)
        diff_tools = toolkit.get_tools()
        if governance_mode is GovernanceMode.ASK:
            diff_tools = gate_tool_if_named(
                diff_tools,
                target_names=DIFF_WRITE_TOOL_NAMES,
                field_name="file_write",
                agent_name=Agents.single_agent,
                api_task_id=options.project_id,
            )
        assembly.add_tools(diff_tools, DiffToolkit.toolkit_name())

    if _enabled(config, "web_fetch"):
        toolkit = WebFetchToolkit(**_options(config, "web_fetch"))
        assembly.toolkits_to_register_agent.append(toolkit)
        assembly.add_tools(toolkit.get_tools(), "WebFetchToolkit")

    if _enabled(config, "planning_worktree"):
        planning_options = {
            "working_directory": working_directory,
            **_options(config, "planning_worktree"),
        }
        toolkit = PlanningWorktreeToolkit(
            **planning_options,
        )
        assembly.add_tools(toolkit.get_tools(), "PlanningWorktreeToolkit")

    if _enabled(config, "mcp"):
        mcp_config = _mcp_config(options, hands)
        if mcp_config is not None:
            mcp_options = {
                "config_dict": mcp_config,
                "timeout": 180,
                **_options(config, "mcp"),
            }
            toolkit = MCPToolkit(**mcp_options)
            try:
                await toolkit.connect()
            except Exception:
                logger.error("Failed to connect MCPToolkit", exc_info=True)
            else:
                assembly.add_tools(toolkit.get_tools(), "MCPToolkit")

    if _enabled(config, "agent") and can_delegate:
        toolkit = DepthLimitedAgentToolkit(
            current_depth=current_depth,
            max_depth=max_depth,
            **_options(config, "agent"),
        )
        assembly.toolkits_to_register_agent.append(toolkit)
        assembly.add_tools(toolkit.get_tools(), toolkit.toolkit_name())

    return assembly
