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

"""Approval-gating wrappers for risky single-agent tools.

- `CommandTier.BLOCKED` (tier 3) is refused before the ApprovalManager is
  consulted. Approval cannot override it.
- `CommandTier.DESTRUCTIVE` (tier 2) prompts in every mode, including AUTO.
- `CommandTier.WORKSPACE_WRITE` (tier 1) prompts in ASK mode only.
- `CommandTier.READ_ONLY` (tier 0) runs directly in every mode.

The wrapper calls `ApprovalManager.request_approval(...)` (which surfaces the
SSE prompt, fires the permission hooks, and waits - bounded by the timeout).
A "denied"/"timeout" decision returns a governance-rejection string as the
tool result so the model can replan instead of failing hard.

The wrapper reaches the per-session `ApprovalManager` the same way other
toolkits reach TaskLock state: `get_task_lock(project_id)` followed by
attribute access. This keeps the wrapper stateless and guarantees it
resolves to the same `ApprovalManager` instance the SSE / HTTP layers use
for the current solve turn.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from enum import Enum
from functools import wraps
from typing import Any

from camel.toolkits import FunctionTool

from app.agent.toolkit.command_policy import (
    CommandScope,
    CommandTier,
    assess_command,
    describe_scope,
    describe_tier,
    summarize_command,
)
from app.agent.toolkit.git_toolkit import (
    WRITE_TOOL_NAMES as GIT_WRITE_TOOL_NAMES,
)
from app.agent.toolkit.github_toolkit import (
    WRITE_TOOL_NAMES as GITHUB_WRITE_TOOL_NAMES,
)
from app.agent.toolkit.mongodb_toolkit import (
    WRITE_TOOL_NAMES as MONGO_WRITE_TOOL_NAMES,
)
from app.service.task import get_task_lock, get_task_lock_if_exists

#: TaskLock attribute holding the session's resolved policy. Written once per
#: solve turn by the single agent and read by every worker/trigger.
SESSION_MODE_ATTR = "governance_mode"

#: Worker tool groups that mirror the single agent's gated surface. Workers
#: build their own toolkits, so without this they could run what the single
#: agent must ask for.
WORKER_GATE_GROUPS: tuple[tuple[str, frozenset[str]], ...] = (
    (
        "terminal",
        frozenset(
            {
                "shell_exec",
                # The terminal toolkit exposes file writes and stdin writes as
                # separate tools, so gating only `shell_exec` left both open.
                "shell_write_content_to_file",
                "shell_write_to_process",
            }
        ),
    ),
    (
        "file_write",
        frozenset(
            {
                "write_to_file",
                "edit_file",
                "notebook_edit_cell",
                "apply_patch",
                "delete_files",
                "restore_backup",
            }
        ),
    ),
    # Workers can run arbitrary Python; the single agent has no equivalent
    # ungated path, so treat it as a workspace write (prompts in Ask).
    ("code_execution", frozenset({"execute_code"})),
    ("git_write", frozenset(GIT_WRITE_TOOL_NAMES)),
    ("github_write", frozenset(GITHUB_WRITE_TOOL_NAMES)),
    ("mongo_write", frozenset(MONGO_WRITE_TOOL_NAMES)),
)

logger = logging.getLogger(__name__)

#: Approvals resolved as anything in this set stop execution.
DENIED_DECISIONS = frozenset({"denied", "timeout", "expired"})

# Non-shell tools: what tier their call represents. github/mongo writes touch
# resources outside the workspace, so they are destructive, not merely writes.
_TIER_BY_FIELD = {
    "file_write": CommandTier.WORKSPACE_WRITE,
    "code_execution": CommandTier.WORKSPACE_WRITE,
    "git_write": CommandTier.WORKSPACE_WRITE,
    "test_generation": CommandTier.WORKSPACE_WRITE,
    "github_write": CommandTier.DESTRUCTIVE,
    "mongo_write": CommandTier.DESTRUCTIVE,
}

_SCOPE_BY_FIELD = {
    "file_write": CommandScope.FILE_WRITES,
    "git_write": CommandScope.GIT_ADD_COMMIT,
    "test_generation": CommandScope.FILE_WRITES,
}

# Terminal tools that are not `shell_exec` and cannot be classified from a
# command line. Without these, `shell_write_content_to_file` ran with no prompt
# even in ASK mode.
_TERMINAL_TOOL_TIERS = {
    "shell_write_content_to_file": CommandTier.WORKSPACE_WRITE,
    # Whatever is written to stdin runs inside a live process (often a shell),
    # so this can execute arbitrary commands. Never suppressible.
    "shell_write_to_process": CommandTier.DESTRUCTIVE,
}


def _command_from(name: str, args: tuple, kwargs: dict) -> str:
    if "command" in kwargs:
        return str(kwargs["command"])
    return str(next((arg for arg in args if isinstance(arg, str)), ""))


def workspace_for_task(api_task_id: str) -> str | None:
    """The run's working directory, when the task lock knows it."""
    task_lock = get_task_lock_if_exists(api_task_id)
    raw = getattr(task_lock, "working_directory", None) if task_lock else None
    return str(raw) if raw else None


def _call_tier(
    field_name: str,
    name: str,
    args: tuple,
    kwargs: dict,
    workspace: str | None = None,
) -> CommandTier:
    """Resolve the tier of one tool call from its live arguments."""
    if name in _TERMINAL_TOOL_TIERS:
        return _TERMINAL_TOOL_TIERS[name]
    if field_name == "terminal" or name == "shell_exec":
        return assess_command(
            _command_from(name, args, kwargs), workspace
        ).tier
    if field_name == "git_write" and name == "git_push":
        return CommandTier.DESTRUCTIVE
    return _TIER_BY_FIELD.get(field_name, CommandTier.WORKSPACE_WRITE)


def _call_scopes(
    field_name: str,
    name: str,
    args: tuple,
    kwargs: dict,
    workspace: str | None = None,
) -> tuple[CommandScope, ...]:
    """Resolve the suppression scopes of one tool call."""
    if name == "shell_write_content_to_file":
        return (CommandScope.FILE_WRITES,)
    if name == "shell_write_to_process":
        return ()
    if field_name == "terminal" or name == "shell_exec":
        return assess_command(
            _command_from(name, args, kwargs), workspace
        ).scopes
    if field_name == "git_write" and name == "git_push":
        return ()
    scope = _SCOPE_BY_FIELD.get(field_name)
    return (scope,) if scope is not None else ()


def _allowed_scopes(task_lock) -> set[str]:
    """Read the task allowlist, defaulting to reads when it is unavailable."""
    getter = getattr(task_lock, "allowed_approval_scopes", None)
    if not callable(getter):
        return {CommandScope.FILE_READS.value}
    try:
        result = getter()
    except Exception:  # pragma: no cover - defensive
        return {CommandScope.FILE_READS.value}
    if not isinstance(result, (set, frozenset, list, tuple)):
        return {CommandScope.FILE_READS.value}
    return {str(scope) for scope in result}


#: Optional model-authored sentence shown on the approval card. Declared in
#: every gated tool's schema, then stripped before the real tool runs.
INTENT_ARG = "intent"
_INTENT_LIMIT = 320
_INTENT_SCHEMA = {
    "type": "string",
    "description": (
        "One short sentence for the person approving this call, written as "
        "'The agent will ...'. Say what this call does and why, in plain "
        "language, naming the files, commands, or external services touched. "
        "Never understate the effect. Do not repeat the raw command."
    ),
}


def _with_intent_argument(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a tool schema with an optional `intent` property.

    The argument is left out of `required`: the deterministic summary stays
    the fallback for calls that do not carry one.
    """
    cloned = copy.deepcopy(schema)
    if not isinstance(cloned, dict):
        return schema
    function = cloned.get("function")
    if not isinstance(function, dict):
        return cloned
    parameters = function.get("parameters")
    if not isinstance(parameters, dict):
        return cloned
    properties = parameters.get("properties")
    if not isinstance(properties, dict):
        return cloned
    properties.setdefault(INTENT_ARG, dict(_INTENT_SCHEMA))
    return cloned


def _normalize_intent(raw: Any) -> str:
    """Turn the model's sentence into one clean line for the card."""
    if not isinstance(raw, str):
        return ""
    text = " ".join(raw.split())
    if not text:
        return ""

    lowered = text.lower()
    for prefix in (
        "i will ",
        "i'll ",
        "i am going to ",
        "i'm going to ",
        "this will ",
        "this command will ",
        "this call will ",
        "the tool will ",
    ):
        if lowered.startswith(prefix):
            text = "The agent will " + text[len(prefix) :]
            break
    else:
        if not lowered.startswith(("the agent ", "agent ", "this agent ")):
            text = "The agent will " + text[0].lower() + text[1:]

    text = text[0].upper() + text[1:]
    if text[-1] not in ".!?":
        text += "."
    if len(text) > _INTENT_LIMIT:
        text = text[: _INTENT_LIMIT - 3].rstrip(" .") + "..."
    return text


def _describe_for_card(
    tier: CommandTier,
    scopes: tuple[CommandScope, ...],
    command: str = "",
    intent: Any = None,
    tool_name: str = "",
) -> str:
    """Intent line under the approval title: what it does, then the risk.

    A model-authored `intent` leads when present. It only replaces the wording,
    never the tier or scopes, which stay derived from the actual call.
    """
    lead = _normalize_intent(intent)
    if not lead and tool_name == "delete_files":
        lead = "The agent will delete the named paths."
    if not lead and tool_name == "restore_backup":
        lead = "The agent will restore a file from a backup copy."
    if not lead:
        summary = summarize_command(command)
        if summary not in {"read files", "write files"}:
            lead = f"The agent will {summary}." if summary else ""

    if tier == CommandTier.DESTRUCTIVE:
        safety = (
            "It changes things outside the workspace or cannot be undone."
        )
    elif tier == CommandTier.READ_ONLY:
        safety = "It only reads your workspace."
    elif scopes == (CommandScope.GIT_ADD_COMMIT,):
        safety = "It stages and commits your changes."
    elif scopes == (CommandScope.DEPENDENCY_INSTALLS,):
        safety = "It installs dependencies in your workspace."
    elif scopes == (CommandScope.BUILDS_TESTS,):
        safety = "It runs a build or test step in your workspace."
    elif CommandScope.CODE_EXECUTION in scopes:
        safety = "It runs code, which could change files."
    elif scopes == (CommandScope.FILE_WRITES,):
        safety = (
            "It deletes the named paths in your workspace."
            if tool_name == "delete_files"
            else "It creates or changes files in your workspace."
        )
    else:
        labels = ", ".join(describe_scope(scope) for scope in scopes)
        safety = (
            f"It may change your workspace: {labels}."
            if labels
            else "It may change your workspace."
        )

    if lead:
        return f"{lead} {safety}"
    return safety


class GovernanceMode(str, Enum):
    """Per-session gating policy for risky tool executions."""

    AUTO = "auto"  # no approval gate (default / ship dark)
    ASK = "ask"  # require explicit human approval before execution

    @classmethod
    def coerce(cls, raw: Any) -> GovernanceMode:
        """Parse a toolkit_config value into a GovernanceMode defensively.

        Unknown / unset values fall back to AUTO so an accidental config
        typo can never lock the agent out of its own tools.
        """
        if isinstance(raw, GovernanceMode):
            return raw
        if isinstance(raw, str):
            value = raw.strip().lower()
            if value in ("ask", "always", "manual", "human"):
                return cls.ASK
        return cls.AUTO


def mode_from_toolkit_config(
    toolkit_config: dict[str, Any] | None,
) -> GovernanceMode:
    """Read `toolkit_config["governance"]["mode"]` the way the assembler does."""
    value = (toolkit_config or {}).get("governance")
    raw = value.get("mode") if isinstance(value, dict) else None
    return GovernanceMode.coerce(raw)


def record_session_governance_mode(
    api_task_id: str, mode: GovernanceMode | str | None
) -> None:
    """Persist the session's policy so workers and triggers gate like the
    single agent. Best-effort: a missing task lock is not an error."""
    task_lock = get_task_lock_if_exists(api_task_id)
    if task_lock is None:
        return
    setattr(task_lock, SESSION_MODE_ATTR, GovernanceMode.coerce(mode).value)


def session_governance_mode(
    api_task_id: str,
    *,
    default: GovernanceMode = GovernanceMode.ASK,
) -> GovernanceMode:
    """Read the policy recorded for this session.

    Defaults to ASK when nothing was recorded: an unknown mode must prompt
    rather than silently run a mutating tool (the hole this closes for
    workers that build their own toolkits).
    """
    task_lock = get_task_lock_if_exists(api_task_id)
    if task_lock is None:
        return default
    raw = getattr(task_lock, SESSION_MODE_ATTR, None)
    if raw is None:
        return default
    return GovernanceMode.coerce(raw)


def gate_tool_if_named(
    tools: list[FunctionTool | Callable],
    *,
    target_names: set[str] | frozenset[str],
    field_name: str,
    agent_name: str,
    api_task_id: str,
    mode: GovernanceMode | None = None,
) -> list[FunctionTool | Callable]:
    """Wrap matching risky tools with an approval gate. Returns new list."""
    gated: list[FunctionTool | Callable] = []
    for tool in tools:
        if (
            isinstance(tool, FunctionTool)
            and tool.get_function_name() in target_names
        ):
            try:
                gated.append(
                    wrap_with_approval(
                        tool,
                        field_name=field_name,
                        agent_name=agent_name,
                        api_task_id=api_task_id,
                        mode=mode,
                    )
                )
                continue
            except Exception as exc:  # pragma: no cover - defensive
                logger.error(
                    "Failed to wrap tool %s with approval gate: %s",
                    tool.get_function_name(),
                    exc,
                )
        gated.append(tool)
    return gated


def gate_worker_tools(
    tools: list[FunctionTool | Callable],
    *,
    api_task_id: str,
    agent_name: str,
    mode: GovernanceMode | None = None,
) -> list[FunctionTool | Callable]:
    """Apply the single agent's approval policy to a worker's tool list.

    Workers (developer, browser, document, multi-modal, social, dynamic
    trigger workers) build their own TerminalToolkit/file/git/connector
    toolkits, so gating only the single agent left them able to run exactly
    what the single agent must ask permission for.
    """
    gated = list(tools)
    for field_name, target_names in WORKER_GATE_GROUPS:
        gated = gate_tool_if_named(
            gated,
            target_names=target_names,
            field_name=field_name,
            agent_name=agent_name,
            api_task_id=api_task_id,
            mode=mode,
        )
    return gated


def wrap_with_approval(
    tool: FunctionTool,
    *,
    field_name: str,
    agent_name: str,
    api_task_id: str,
    mode: GovernanceMode | None = None,
) -> FunctionTool:
    """Wrap a `FunctionTool` so it requests approval before execution.

    Returns a NEW `FunctionTool`; the caller replaces the original in the
    assembled tool list. The wrapped tool preserves the original schema apart
    from adding the optional `intent` sentence the model writes for the
    approval card; that argument is stripped before the real tool runs.

    Args:
        tool: The original FunctionTool to gate.
        field_name: Human-readable label for the SSE prompt, e.g.
            "terminal" or "file_write".
        agent_name: Agent label surfaced in the approval request.
        api_task_id: Project id used to resolve the TaskLock /
            ApprovalManager.
        mode: Session policy. When omitted, resolved per call from the task
            lock so a worker built before the turn's policy is known still
            gates correctly. Falls back to ASK.

    Returns:
        A new FunctionTool that first gates through the ApprovalManager and
        only executes the underlying tool when approved.
    """
    name = tool.get_function_name()
    # Preserve the FULL OpenAI tool schema (type + function wrapper), not the
    # inner function dict, so the replacement FunctionTool validates and
    # serializes identically to the original. The one addition is the optional
    # model-authored `intent` sentence for the approval card.
    schema = _with_intent_argument(tool.openai_tool_schema)

    @wraps(_wrapped_func(tool))
    async def _gated(*args: Any, **kwargs: Any) -> str:
        intent = kwargs.pop(INTENT_ARG, None)
        workspace = workspace_for_task(api_task_id)
        tier = _call_tier(field_name, name, args, kwargs, workspace)
        scopes = _call_scopes(field_name, name, args, kwargs, workspace)
        # Resolved per call, not at construction: a worker may be built
        # before its turn's mode is recorded, and the mode can change
        # between turns on a reused agent.
        effective_mode = (
            mode if mode is not None else session_governance_mode(api_task_id)
        )

        if tier == CommandTier.BLOCKED:
            logger.info(
                "Blocked tier-3 tool action %s",
                name,
                extra={
                    "governance": "blocked",
                    "tier": int(tier),
                    "project_id": api_task_id,
                },
            )
            return (
                f"[SYSTEM GOVERNANCE]: the requested '{name}' action is "
                "blocked by policy (tier 3). Approval cannot override it. "
                "Use a non-destructive alternative, or ask the user to do it."
            )

        task_lock = None
        suppressed = False
        if scopes and tier <= CommandTier.WORKSPACE_WRITE:
            try:
                task_lock = get_task_lock(api_task_id)
            except Exception:  # pragma: no cover - defensive
                task_lock = None
            if task_lock is not None:
                allowed = _allowed_scopes(task_lock)
                suppressed = all(
                    scope.value in allowed for scope in scopes
                )

        needs_approval = tier >= CommandTier.DESTRUCTIVE or (
            effective_mode == GovernanceMode.ASK
            and tier >= CommandTier.WORKSPACE_WRITE
        )
        if suppressed:
            needs_approval = False
        elif (
            tier == CommandTier.READ_ONLY
            and CommandScope.FILE_READS in scopes
            and CommandScope.FILE_READS.value not in _allowed_scopes(task_lock)
        ):
            # Privacy switch: reads prompt in every mode once the user
            # removes File reads from this task's allowlist. Other read-only
            # scopes (builds/tests, searches) must not trigger it.
            needs_approval = True

        if not needs_approval:
            return await tool.async_call(*args, **kwargs)

        # Resolve the live per-session manager. If unavailable mid-run, fail
        # closed: surface the lack of gate rather than silently executing a
        # mutating command.
        if task_lock is None:
            try:
                task_lock = get_task_lock(api_task_id)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error(
                    "Governance gate unavailable (no task lock); "
                    "refusing to run %s: %s",
                    field_name,
                    exc,
                )
                return (
                    "[SYSTEM GOVERNANCE]: approval gate unavailable for "
                    f"'{field_name}'. Refusing to run the mutating action "
                    "until the session is healthy."
                )

        manager = getattr(task_lock, "approval_manager", None)
        if manager is None:  # pragma: no cover - should never happen live
            logger.error(
                "Governance gate unavailable (no ApprovalManager); "
                "refusing to run %s",
                field_name,
            )
            return (
                "[SYSTEM GOVERNANCE]: approval gate not initialised for "
                f"'{field_name}'. Refusing to run the mutating action."
            )

        detail = _describe_call(name, args, kwargs)
        decision = await manager.request_approval(
            tool_name=field_name,
            detail=detail,
            agent_name=agent_name,
            tier=int(tier),
            tier_label=describe_tier(tier),
            scopes=[scope.value for scope in scopes],
            description=_describe_for_card(
                tier,
                scopes,
                _command_from(name, args, kwargs)
                if field_name == "terminal" or name == "shell_exec"
                else "",
                intent=intent,
                tool_name=name,
            ),
        )

        if decision in DENIED_DECISIONS:
            reason = (
                "the approval request expired"
                if decision in ("timeout", "expired")
                else "denied"
            )
            logger.info(
                "Mutating tool action %s %s",
                name,
                reason,
                extra={
                    "governance": "denied",
                    "decision": decision,
                    "project_id": api_task_id,
                },
            )
            return (
                f"[SYSTEM GOVERNANCE]: the requested '{name}' action was "
                f"{reason} by a human. Stop and reconsider your plan; do not "
                "retry the same mutating action in this step. Offer a "
                "revised, non-mutating next step or ask the user what they "
                "prefer."
            )

        # Approved: actually run the underlying tool.
        try:
            result = await tool.async_call(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - surface, don't swallow
            logger.warning(
                "Approved mutating tool %s raised: %s",
                name,
                exc,
            )
            raise
        return result

    # `@wraps(_wrapped_func(tool))` copies `__wrapped__` = the ORIGINAL tool's
    # (usually sync) callable onto `_gated`. CAMEL's `FunctionTool.is_async`
    # is `iscoroutinefunction(inspect.unwrap(self.func))` -- `inspect.unwrap`
    # follows `__wrapped__` back to that sync original, so it reports the gated
    # tool as SYNC even though `_gated` is a coroutine. That routes execution
    # down CAMEL's synchronous path, which runs the coroutine on a separate
    # persistent loop via `run_coroutine_threadsafe(...).result()` -- a BLOCKING
    # call that freezes the SSE event loop for the entire approval wait, so the
    # `approval_request` frame can't be flushed until the tool call returns
    # (i.e. only when the approval times out). Drop `__wrapped__` so `inspect.unwrap`
    # stops at `_gated` (a coroutine function) and `is_async` is True, keeping
    # the gated tool on the async, non-blocking execution path.
    if hasattr(_gated, "__wrapped__"):
        del _gated.__wrapped__

    gated_tool = FunctionTool(
        _gated,
        openai_tool_schema=schema,
    )
    # Which policy field gated this tool; used by tests and diagnostics.
    try:
        gated_tool._governance_field = field_name
    except (AttributeError, TypeError):  # pragma: no cover - defensive
        pass
    return gated_tool


def _wrapped_func(tool: FunctionTool) -> Callable | None:
    """Return the underlying callable of a FunctionTool for @wraps."""
    return getattr(tool, "func", None)


#: Payload arguments the user must see in full on the card. The 200-char cap
#: cut long shell commands mid-token, which made the prompt unusable.
_VERBATIM_ARG_KEYS = frozenset(
    {"command", "cmd", "code", "script", "content", "query", "sql", "paths"}
)
_CALL_ARG_LIMIT = 200
_VERBATIM_LIMIT = 8000


def _describe_call(name: str, args: tuple, kwargs: dict) -> str:
    """Build a human-readable view of the pending tool call."""
    parts: list[str] = [
        _shorten(repr(value), _VERBATIM_LIMIT) for value in args
    ]
    for key, value in kwargs.items():
        if key in ("working_directory", "cwd") and isinstance(value, str):
            parts.append(f"{key}=<dir>")
            continue
        limit = (
            _VERBATIM_LIMIT if key in _VERBATIM_ARG_KEYS else _CALL_ARG_LIMIT
        )
        parts.append(f"{key}={_shorten(repr(value), limit)}")
    body = ", ".join(parts) if parts else "(no arguments)"
    return f"{name}({body})"


def _shorten(text: str, limit: int = 200) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
