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
)
from app.service.task import get_task_lock

logger = logging.getLogger(__name__)

#: Approvals resolved as anything in this set stop execution.
DENIED_DECISIONS = frozenset({"denied", "timeout", "expired"})

# Non-shell tools: what tier their call represents. github/mongo writes touch
# resources outside the workspace, so they are destructive, not merely writes.
_TIER_BY_FIELD = {
    "file_write": CommandTier.WORKSPACE_WRITE,
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


def _command_from(name: str, args: tuple, kwargs: dict) -> str:
    if "command" in kwargs:
        return str(kwargs["command"])
    return str(next((arg for arg in args if isinstance(arg, str)), ""))


def _call_tier(
    field_name: str, name: str, args: tuple, kwargs: dict
) -> CommandTier:
    """Resolve the tier of one tool call from its live arguments."""
    if field_name == "terminal" or name == "shell_exec":
        return assess_command(_command_from(name, args, kwargs)).tier
    if field_name == "git_write" and name == "git_push":
        return CommandTier.DESTRUCTIVE
    return _TIER_BY_FIELD.get(field_name, CommandTier.WORKSPACE_WRITE)


def _call_scopes(
    field_name: str, name: str, args: tuple, kwargs: dict
) -> tuple[CommandScope, ...]:
    """Resolve the suppression scopes of one tool call."""
    if field_name == "terminal" or name == "shell_exec":
        return assess_command(_command_from(name, args, kwargs)).scopes
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


def _describe_for_card(
    tier: CommandTier, scopes: tuple[CommandScope, ...]
) -> str:
    """One-line explanation rendered under the approval title."""
    if tier == CommandTier.DESTRUCTIVE:
        return (
            "This command changes things outside the workspace or cannot "
            "be undone."
        )
    if tier == CommandTier.WORKSPACE_WRITE:
        if scopes == (CommandScope.GIT_ADD_COMMIT,):
            return "This command stages and commits your changes."
        if scopes == (CommandScope.DEPENDENCY_INSTALLS,):
            return "This command installs dependencies in your workspace."
        if scopes == (CommandScope.BUILDS_TESTS,):
            return "This command runs a build or test step in your workspace."
        if scopes == (CommandScope.FILE_WRITES,):
            return "This command creates or changes files in your workspace."
        labels = ", ".join(describe_scope(scope) for scope in scopes)
        if labels:
            return f"This command changes your workspace: {labels}."
        return "This command changes your workspace."
    if tier == CommandTier.READ_ONLY:
        return "This command only reads your workspace."
    return ""


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


def wrap_with_approval(
    tool: FunctionTool,
    *,
    field_name: str,
    agent_name: str,
    api_task_id: str,
    mode: GovernanceMode = GovernanceMode.ASK,
) -> FunctionTool:
    """Wrap a `FunctionTool` so it requests approval before execution.

    Returns a NEW `FunctionTool`; the caller replaces the original in the
    assembled tool list. The wrapped tool preserves the original's schema
    (name/description/parameters) so the model-facing contract is
    unchanged - only the runtime behavior is gated.

    Args:
        tool: The original FunctionTool to gate.
        field_name: Human-readable label for the SSE prompt, e.g.
            "terminal" or "file_write".
        agent_name: Agent label surfaced in the approval request.
        api_task_id: Project id used to resolve the TaskLock /
            ApprovalManager.
        mode: Session policy. Defaults to ASK so a caller that wraps a tool
            without saying otherwise keeps the prompt-always behavior.

    Returns:
        A new FunctionTool that first gates through the ApprovalManager and
        only executes the underlying tool when approved.
    """
    name = tool.get_function_name()
    # Preserve the FULL OpenAI tool schema (type + function wrapper), not the
    # inner function dict, so the replacement FunctionTool validates and
    # serializes identically to the original.
    schema = tool.openai_tool_schema

    @wraps(_wrapped_func(tool))
    async def _gated(*args: Any, **kwargs: Any) -> str:
        tier = _call_tier(field_name, name, args, kwargs)
        scopes = _call_scopes(field_name, name, args, kwargs)

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
            mode == GovernanceMode.ASK
            and tier >= CommandTier.WORKSPACE_WRITE
        )
        if suppressed:
            needs_approval = False
        elif tier == CommandTier.READ_ONLY and scopes:
            # Privacy switch: reads prompt in every mode once the user
            # removes File reads from this task's allowlist.
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
            description=_describe_for_card(tier, scopes),
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

    return FunctionTool(
        _gated,
        openai_tool_schema=schema,
    )


def _wrapped_func(tool: FunctionTool) -> Callable | None:
    """Return the underlying callable of a FunctionTool for @wraps."""
    return getattr(tool, "func", None)


def _describe_call(name: str, args: tuple, kwargs: dict) -> str:
    """Build a short human-readable summary of the pending tool call."""
    parts: list[str] = []
    for value in args:
        parts.append(_shorten(repr(value)))
    for key, value in kwargs.items():
        if key in ("working_directory", "cwd") and isinstance(value, str):
            parts.append(f"{key}=<dir>")
            continue
        parts.append(f"{key}={_shorten(repr(value))}")
    body = ", ".join(parts) if parts else "(no arguments)"
    return f"{name}({body})"


def _shorten(text: str, limit: int = 200) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
