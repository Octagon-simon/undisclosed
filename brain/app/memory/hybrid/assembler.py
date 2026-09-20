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

"""Context assembly under an explicit token budget (§24-27).

The final prompt is structured into clearly separated, tagged sections so the
model can tell instructions from evidence from current state:

    <memory_rules> <historical_evidence> <active_memory> <working_memory>
    <recent_conversation>

Each section gets a share of the budget that *shifts with the query type* (§25):
an exact-recall query buys more historical evidence, a continuation buys more
recent + working context, a simple request retrieves almost nothing. Sections
shrink or drop entirely when they have nothing to say, so the block never
carries empty scaffolding.
"""

from __future__ import annotations

from app.memory.events import ConversationEvent
from app.memory.hybrid import text as T
from app.memory.hybrid.config import section_budget_fractions, token_estimate
from app.memory.hybrid.schema import (
    LEVEL_EXACT,
    LEVEL_RECENT,
    RetrievalResult,
    RetrievedItem,
)

_INSTRUCTIONS = (
    "Memory rules: prefer exact historical evidence for exact-history "
    "questions; prefer active memory for current state; treat superseded "
    "memory as historical, not current; use recent conversation to resolve "
    "pronouns; never invent a detail that is not in the evidence, and say the "
    "detail could not be recovered when it is absent."
)


def _fractions_for(level: int) -> dict[str, float]:
    fractions = dict(section_budget_fractions())
    if level == LEVEL_EXACT:
        fractions["exact"] = min(0.30, fractions["exact"] + 0.20)
        fractions["historical"] = min(0.40, fractions["historical"] + 0.10)
        fractions["recent"] = max(0.15, fractions["recent"] - 0.20)
    elif level == LEVEL_RECENT:
        fractions["recent"] = min(0.70, fractions["recent"] + 0.30)
        fractions["working_memory"] = fractions["working_memory"] + 0.05
        # Continuation needs no history search at all (§38): zero both the
        # exact and episode lanes so stale episodes can't leak in as context.
        fractions["exact"] = 0.0
        fractions["historical"] = 0.0
    return fractions


def _char_budget(total_tokens: int, fraction: float) -> int:
    return max(0, int(total_tokens * fraction * 4))


def _render_episodes(items: list[RetrievedItem], budget_chars: int) -> str:
    if not items or budget_chars <= 0:
        return ""
    lines: list[str] = []
    used = 0
    for item in items:
        block = item.text.strip()
        if used + len(block) > budget_chars and lines:
            break
        lines.append(T.truncate(block, max(0, budget_chars - used)))
        used += len(block)
    return "\n\n".join(lines)


def _render_memories(
    active: list[RetrievedItem], superseded: list[RetrievedItem], budget_chars: int
) -> str:
    if (not active and not superseded) or budget_chars <= 0:
        return ""
    lines: list[str] = []
    if active:
        lines.append("Current:")
        for item in active:
            lines.append(f"- {item.text}")
    if superseded:
        lines.append("Historical (superseded, no longer current):")
        for item in superseded:
            lines.append(f"- {item.text}")
    return T.truncate("\n".join(lines), budget_chars)


def _render_working_memory(result: RetrievalResult, budget_chars: int) -> str:
    wm = result.working_memory
    if wm is None or wm.is_empty() or budget_chars <= 0:
        return ""
    lines: list[str] = []
    if wm.current_task:
        lines.append(f"Current task: {wm.current_task}")
    if wm.current_goal:
        lines.append(f"Goal: {wm.current_goal}")
    if wm.decisions:
        lines.append("Decisions: " + "; ".join(wm.decisions))
    if wm.constraints:
        lines.append("Constraints: " + "; ".join(wm.constraints))
    if wm.open_questions:
        lines.append("Open questions: " + "; ".join(wm.open_questions))
    if wm.current_status:
        lines.append(f"Status: {wm.current_status}")
    if wm.next_step:
        lines.append(f"Next step: {wm.next_step}")
    return T.truncate("\n".join(lines), budget_chars)


def _render_evidence(items: list[RetrievedItem], budget_chars: int) -> str:
    """Render raw-message evidence. ``item.text`` is pre-rendered by the engine
    as ``Turn N (Role): content`` so the turn/source stays visible (§23)."""

    if not items or budget_chars <= 0:
        return ""
    lines: list[str] = []
    used = 0
    for item in items:
        line = f"- {item.text.strip()}"
        if used + len(line) > budget_chars and lines:
            break
        lines.append(T.truncate(line, max(0, budget_chars - used)))
        used += len(line)
    return "\n".join(lines)


def _render_recent(
    events: list[ConversationEvent], budget_chars: int
) -> str:
    if not events or budget_chars <= 0:
        return ""
    kept: list[str] = []
    used = 0
    for event in reversed(events):
        line = f"{event.role.capitalize()}: {T.collapse(event.content)}"
        if used + len(line) > budget_chars and kept:
            break
        kept.append(T.truncate(line, max(0, budget_chars - used)))
        used += len(line)
    kept.reverse()
    return "\n".join(kept)


def _section(tag: str, body: str) -> str:
    body = body.strip()
    if not body:
        return ""
    return f"<{tag}>\n{body}\n</{tag}>"


def assemble(
    result: RetrievalResult,
    *,
    recent_events: list[ConversationEvent],
    token_budget: int,
    include_instructions: bool = True,
) -> str:
    """Render the retrieved state into the tagged context block.

    Sections are emitted in the §24 order. Within the historical + exact budget
    the model is told to prefer exact evidence over an approximate summary,
    which is how the "grounded evidence" rule (§26) is enforced structurally
    rather than hoped for.
    """

    fractions = _fractions_for(result.plan.level)

    blocks: list[str] = []
    if include_instructions:
        blocks.append(
            _section(
                "memory_rules",
                T.truncate(
                    _INSTRUCTIONS,
                    _char_budget(token_budget, fractions["instructions"]),
                ),
            )
        )

    historical = _render_episodes(
        result.episodes, _char_budget(token_budget, fractions["historical"])
    )
    blocks.append(_section("historical_evidence", historical))

    exact = _render_evidence(
        result.messages, _char_budget(token_budget, fractions["exact"])
    )
    if exact:
        blocks.append(
            _section(
                "exact_historical_evidence",
                "Prefer this verbatim evidence over any summary.\n" + exact,
            )
        )
    elif result.plan.use_exact and result.evidence_found == "none":
        blocks.append(
            _section(
                "exact_historical_evidence",
                "No exact evidence was retrieved for this request; state that "
                "the exact detail could not be recovered rather than guessing.",
            )
        )

    blocks.append(
        _section(
            "active_memory",
            _render_memories(
                result.active_memories,
                result.superseded_memories,
                _char_budget(token_budget, fractions["active_memory"]),
            ),
        )
    )
    blocks.append(
        _section(
            "working_memory",
            _render_working_memory(
                result, _char_budget(token_budget, fractions["working_memory"])
            ),
        )
    )
    blocks.append(
        _section(
            "recent_conversation",
            _render_recent(
                recent_events,
                _char_budget(token_budget, fractions["recent"]),
            ),
        )
    )

    rendered = "\n\n".join(b for b in blocks if b.strip())
    return rendered


def estimate_tokens(rendered: str) -> int:
    return token_estimate(rendered)
