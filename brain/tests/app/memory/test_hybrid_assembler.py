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

"""Context assembler tests: section separation, budgets, grounding (§24-27)."""

from __future__ import annotations

from app.memory.events import ConversationEvent
from app.memory.hybrid import assembler
from app.memory.hybrid.schema import (
    LEVEL_EXACT,
    LEVEL_RECENT,
    RetrievalPlan,
    RetrievalResult,
    RetrievedItem,
    WorkingMemory,
)


def _event(content: str, role: str = "user") -> ConversationEvent:
    return ConversationEvent(
        event_id="e",
        run_id="r",
        timestamp="t",
        role=role,  # type: ignore[arg-type]
        content=content,
        source="chat",
        visibility="context",
        hash="sha256:x",
    )


def _result(**kwargs) -> RetrievalResult:
    plan = kwargs.pop("plan", RetrievalPlan(level=LEVEL_EXACT, use_exact=True))
    return RetrievalResult(plan=plan, **kwargs)


class TestSections:
    def test_all_sections_present_and_separated(self):
        result = _result(
            episodes=[
                RetrievedItem(
                    kind="episode",
                    id="ep_1",
                    text='Episode "Auth" (turns 1-4):\nObjective: design auth',
                )
            ],
            messages=[
                RetrievedItem(
                    kind="message",
                    id="m1",
                    text="Turn 4 (assistant): port 8080",
                )
            ],
            active_memories=[
                RetrievedItem(kind="memory", id="mem1", text="database = PostgreSQL")
            ],
            working_memory=WorkingMemory(
                conversation_id="c", current_task="fix pagination"
            ),
            evidence_found="exact",
        )
        rendered = assembler.assemble(
            result,
            recent_events=[_event("what port do we use?")],
            token_budget=4000,
        )
        for tag in (
            "memory_rules",
            "historical_evidence",
            "exact_historical_evidence",
            "active_memory",
            "working_memory",
            "recent_conversation",
        ):
            assert f"<{tag}>" in rendered
        assert "Prefer this verbatim evidence" in rendered
        assert "database = PostgreSQL" in rendered
        assert "Current task: fix pagination" in rendered

    def test_superseded_marked_historical(self):
        result = _result(
            active_memories=[
                RetrievedItem(kind="memory", id="m2", text="database = PostgreSQL")
            ],
            superseded_memories=[
                RetrievedItem(kind="memory", id="m1", text="database = MongoDB")
            ],
        )
        rendered = assembler.assemble(
            result, recent_events=[], token_budget=4000
        )
        assert "Current:" in rendered
        assert "Historical (superseded" in rendered
        assert "MongoDB" in rendered

    def test_missing_exact_evidence_adds_not_found_note(self):
        result = _result(messages=[], evidence_found="none")
        rendered = assembler.assemble(
            result,
            recent_events=[_event("what commit hash did I give you?")],
            token_budget=4000,
        )
        assert "could not be recovered" in rendered

    def test_continuation_drops_history_keeps_recent(self):
        plan = RetrievalPlan(level=LEVEL_RECENT, use_recent=True)
        result = _result(
            plan=plan,
            episodes=[
                RetrievedItem(kind="episode", id="ep1", text="Episode old thing")
            ],
        )
        rendered = assembler.assemble(
            result,
            recent_events=[_event("continue")],
            token_budget=4000,
        )
        assert "recent_conversation" in rendered
        assert "Episode old thing" not in rendered

    def test_budget_bounds_oversized_recent(self):
        huge = "x" * 20000
        rendered = assembler.assemble(
            _result(messages=[], evidence_found="none"),
            recent_events=[_event(huge)],
            token_budget=50,
        )
        # Section budget is ~40% of 50 tokens ~ 80 chars; allow generous slack
        # for tags/instructions but far below the 20k input.
        assert len(rendered) < 2000

    def test_instructions_can_be_omitted(self):
        rendered = assembler.assemble(
            _result(messages=[], evidence_found="none"),
            recent_events=[],
            token_budget=4000,
            include_instructions=False,
        )
        assert "<memory_rules>" not in rendered
