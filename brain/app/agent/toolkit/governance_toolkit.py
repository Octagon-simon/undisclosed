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

"""Approval-gating wrappers for risky single-agent tools.

- `GovernanceMode.AUTO` (default): no gating. Tools execute directly,
  identical to today's behavior. The feature ships dark - flipped per
  session via `toolkit_config`, never on by default.
- `GovernanceMode.ASK`: mutating tools (terminal, write_to_file) require
  explicit human approval before the underlying tool runs. The wrapper calls
  `ApprovalManager.request_approval(...)` (which surfaces the SSE prompt,
  fires the permission hooks, and waits - bounded by the timeout). A
  "denied"/"timeout" decision returns a governance-rejection string as the
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

from app.service.task import get_task_lock

logger = logging.getLogger(__name__)

#: Approvals resolved as anything in this set stop execution.
DENIED_DECISIONS = frozenset({"denied", "timeout"})


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
        # Resolve the live per-session manager. If unavailable mid-run, fail
        # closed: surface the lack of gate rather than silently executing a
        # mutating command.
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
                f"'{field_name}'. Refusing to run the mutating action until "
                "the session is healthy."
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
        )

        if decision in DENIED_DECISIONS:
            reason = (
                "the request timed out" if decision == "timeout" else "denied"
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
    # (i.e. only at the 120s timeout). Drop `__wrapped__` so `inspect.unwrap`
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
