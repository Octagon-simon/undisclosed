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

"""Always-on persistent rules (the "standing constraints" block).

A rule is not a second store: it is an active ``StructuredMemory`` of type
``constraint``. This module only answers two questions, on every turn:

* which active constraints apply to this thread (project + user + this
  conversation), independent of the query, the router, or Chroma;
* how those rules render into the prompt, and when the agent should double-check
  its recall instead of trusting the block.

There is deliberately no cache. A cache that can go empty or stale is exactly
how a standing rule gets lost, and two small JSON reads per turn are cheap.
"""

from __future__ import annotations

import logging
import re

from app.memory.hybrid import canonical, text as T
from app.memory.hybrid.schema import (
    SCOPE_CONVERSATION,
    SCOPE_GLOBAL,
    SCOPE_PROJECT,
    StructuredMemory,
)
from app.memory.hybrid.scope import GlobalMemoryStore
from app.memory.hybrid.storage import HybridStore

logger = logging.getLogger("memory.hybrid.rules")

_RULE_TEXT_MAX_CHARS = 400
_PROBE_EVERY_TURNS = 10
# Legacy extraction produced project-level fragments ("not describe it") that
# were never rules. Project/conversation constraints written before severity
# existed have to clear a small quality bar before they become always-on.
_RULE_MIN_CHARS = 20
_RULE_MIN_WORDS = 3
_WEAK_RULE_WORDS = frozenset(
    {"not", "never", "always", "again", "that", "this", "it", "them", "about"}
)
_SCOPE_RANK = {SCOPE_GLOBAL: 1, SCOPE_PROJECT: 2, SCOPE_CONVERSATION: 3}
_HEADER = (
    "Standing constraints from this user. Treat every rule in this block as a "
    "requirement on every action in this turn, regardless of what the current "
    "request asks for; [hard] rules are non-negotiable. If two rules conflict, "
    "stop and ask instead of choosing."
)
_RECALL_QUERY = "standing rules constraints preferences"


def read_active_rules(
    base_store,
    *,
    user_key: str,
    space_id: str,
    project_id: str,
    conversation_id: str,
) -> list[StructuredMemory]:
    """Every active constraint that applies to this thread, hard-first.

    Reads the same two records the injected memory already consults: the current
    project's ``memories.json`` and the user-level ``GlobalMemoryStore`` file.
    No Chroma, no query matching, no lane gating, no cache.
    """

    #a request may omit space_id; the run context already resolves it this way,
    #but a direct caller must not silently lose its project rules.
    space_id = space_id or project_id

    candidates: list[StructuredMemory] = []
    try:
        candidates.extend(
            HybridStore(base_store).read_active_memories(
                user_key, space_id, project_id
            )
        )
    except Exception:  # noqa: BLE001 - best-effort read
        logger.debug("rules: project memory read failed", exc_info=True)
    try:
        candidates.extend(
            GlobalMemoryStore(base_store).read_active_memories(
                user_key, space_id, project_id
            )
        )
    except Exception:  # noqa: BLE001 - best-effort read
        logger.debug("rules: global memory read failed", exc_info=True)

    by_key: dict[str, StructuredMemory] = {}
    for memory in candidates:
        if memory.status != "active":
            continue
        if (memory.type or "").strip().lower() != "constraint":
            continue
        if (
            memory.scope_type == SCOPE_CONVERSATION
            and memory.scope_id not in ("", conversation_id)
        ):
            continue
        if not _is_usable_rule(memory):
            continue
        identity = canonical.normalize_key(memory.key) or canonical.normalize_key(
            memory.value
        )
        current = by_key.get(identity)
        if current is None or _precedence(memory) > _precedence(current):
            by_key[identity] = memory

    rules = list(by_key.values())
    rules.sort(
        key=lambda m: (
            0 if m.severity == "hard" else 1,
            m.category or "zz",
            m.key,
        )
    )
    return rules


def _is_usable_rule(memory: StructuredMemory) -> bool:
    """Hard rules and user-level rules always load; legacy project rows must earn it."""

    if memory.severity == "hard" or memory.scope_type == SCOPE_GLOBAL:
        return True
    text = T.collapse(memory.value)
    if len(text) < _RULE_MIN_CHARS:
        return False
    words = re.findall(r"[a-z0-9][a-z0-9_./-]*", text.lower())
    content = [w for w in words if len(w) > 2 and w not in _WEAK_RULE_WORDS]
    return len(content) >= _RULE_MIN_WORDS


def _precedence(memory: StructuredMemory) -> tuple[int, str]:
    """Conversation > project > global for the same key, newest first."""

    return (
        _SCOPE_RANK.get(memory.scope_type, 0),
        memory.updated_at or memory.created_at or "",
    )


def _rule_line(memory: StructuredMemory) -> str:
    severity = "hard" if memory.severity == "hard" else "soft"
    category = memory.category or "general"
    scope = memory.scope_type or SCOPE_PROJECT
    stated = (memory.last_confirmed_at or memory.created_at or "")[:10]
    text = T.truncate(T.collapse(memory.value), _RULE_TEXT_MAX_CHARS)
    suffix = f" (stated {stated})" if stated else ""
    return f"- [{severity}][{category}][{scope}] {text}{suffix}"


def render_rules_block(
    rules: list[StructuredMemory], *, budget_chars: int
) -> str:
    """Render ``<persistent_rules>``; empty string when there are no rules.

    Hard rules are never dropped to fit the budget. Soft rules fill what is left,
    newest first, so the oldest soft rule is the first to go.
    """

    if not rules:
        return ""
    hard = [r for r in rules if r.severity == "hard"]
    soft = [r for r in rules if r.severity != "hard"]
    soft.sort(key=lambda m: m.updated_at or m.created_at or "", reverse=True)

    lines: list[str] = []
    used = 0
    for memory in [*hard, *soft]:
        line = _rule_line(memory)
        if memory.severity != "hard" and budget_chars > 0:
            if used + len(line) > budget_chars and lines:
                break
        lines.append(line)
        used += len(line)
    body = _HEADER + "\n" + "\n".join(lines)
    return f"<persistent_rules>\n{body}\n</persistent_rules>"


def should_probe(rules: list[StructuredMemory], turn_index: int) -> bool:
    """Whether this turn should ask the agent to verify its recall.

    Two triggers, both cheap: nothing loaded, or every tenth user turn. A turn
    index of 0 (unknown/not counted) only probes when the block is empty.
    """

    if not rules:
        return True
    return turn_index > 0 and turn_index % _PROBE_EVERY_TURNS == 0


def render_recall_check(*, empty_block: bool) -> str:
    """The small probe block; wording forbids claiming an unverified rule."""

    if empty_block:
        ask = (
            "No standing rules were loaded for this turn. Call "
            f'recall_facts("{_RECALL_QUERY}") once before acting. '
            "If the tool returns nothing, do not claim to remember a rule."
        )
    else:
        ask = (
            "Periodic memory check: call "
            f'recall_facts("{_RECALL_QUERY}") once and confirm internally that '
            "no standing rule is missing from the block above. Do not narrate "
            "this check. If the tool returns nothing, do not claim to remember "
            "a rule."
        )
    return f"<recall_check>\n{ask}\n</recall_check>"
