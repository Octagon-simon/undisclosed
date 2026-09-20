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

"""Extractor tests: eviction, boundaries, episodes, memory ops, working memory."""

from __future__ import annotations

from app.memory.events import ConversationEvent
from app.memory.hybrid import extractor
from app.memory.hybrid.schema import WorkingMemory


def _event(i: int, role: str, content: str) -> ConversationEvent:
    return ConversationEvent(
        event_id=f"evt_{i}",
        run_id=f"run_{i}",
        timestamp="t",
        role=role,  # type: ignore[arg-type]
        content=content,
        source="chat",
        visibility="context",
        hash="sha256:x",
    )


def _topic_events() -> list[ConversationEvent]:
    return [
        _event(1, "user", "design the authentication flow"),
        _event(2, "assistant", "use JWT with refresh tokens"),
        _event(3, "user", "what port should the server use"),
        _event(4, "assistant", "port 8080 for local development"),
        _event(5, "user", "explain database schema"),
        _event(6, "assistant", "tables for users and sessions"),
    ]


class TestEviction:
    def test_no_eviction_when_window_covers_all(self):
        plan = extractor.plan_eviction(
            _topic_events(),
            covered_through_turn=0,
            budget_tokens=10000,
            soft=0.8,
            hard=1.0,
        )
        assert plan.evict_through_turn == 0

    def test_hard_threshold_forces_deterministic_cut(self):
        plan = extractor.plan_eviction(
            _topic_events(),
            covered_through_turn=0,
            budget_tokens=5,
            soft=0.8,
            hard=1.0,
        )
        assert plan.forced is True
        assert plan.evict_through_turn == plan.recent_start_turn - 1

    def test_soft_threshold_prefers_boundary(self):
        plan = extractor.plan_eviction(
            _topic_events(),
            covered_through_turn=0,
            budget_tokens=10,
            soft=0.0,
            hard=10.0,
        )
        assert plan.forced is False
        assert plan.boundary_turn is not None
        assert plan.evict_through_turn == 2

    def test_never_evicts_past_coverage(self):
        plan = extractor.plan_eviction(
            _topic_events(),
            covered_through_turn=4,
            budget_tokens=5,
            soft=0.8,
            hard=1.0,
        )
        assert plan.evict_through_turn >= 4


class TestBoundary:
    def test_finds_topic_change_boundary(self):
        boundary = extractor.find_boundary(_topic_events(), 1, 3)
        assert boundary == 2

    def test_no_boundary_in_short_range(self):
        assert extractor.find_boundary(_topic_events(), 1, 1) is None

    def test_completion_cue_is_boundary(self):
        events = [
            _event(1, "user", "add the tests"),
            _event(2, "assistant", "All done. The tests pass."),
            _event(3, "user", "add the tests"),
        ]
        assert extractor.find_boundary(events, 1, 2) == 2


class TestEpisodes:
    def test_episode_preserves_decision_constraint_and_sources(self):
        events = [
            _event(1, "user", "we'll use PostgreSQL for the database"),
            _event(2, "assistant", "Good choice."),
            _event(3, "user", "don't change the existing UI"),
        ]
        episode = extractor.build_episode(
            events, conversation_id="c", start_turn=1, end_turn=3, now="t"
        )
        assert "PostgreSQL" in episode.summary
        assert "Decisions:" in episode.summary
        assert "Constraints:" in episode.summary
        assert episode.source_message_ids == ["evt_1", "evt_2", "evt_3"]
        assert episode.start_turn == 1 and episode.end_turn == 3

    def test_build_episodes_splits_on_topic_change(self):
        events = [
            _event(1, "user", "design the authentication flow"),
            _event(2, "assistant", "use JWT with refresh tokens"),
            _event(3, "user", "explain the database schema"),
            _event(4, "assistant", "tables for users and sessions"),
        ]
        episodes = extractor.build_episodes(
            events, start_turn=1, end_turn=4, conversation_id="c", now="t"
        )
        assert len(episodes) == 2
        assert episodes[0].start_turn == 1 and episodes[0].end_turn == 2
        assert episodes[1].start_turn == 3 and episodes[1].end_turn == 4

    def test_episodes_are_independent_not_recursive(self):
        events = [
            _event(1, "user", "first topic alpha"),
            _event(2, "assistant", "reply alpha"),
            _event(3, "user", "second topic beta"),
            _event(4, "assistant", "reply beta"),
        ]
        episodes = extractor.build_episodes(
            events, start_turn=1, end_turn=4, conversation_id="c", now="t"
        )
        # Each episode only summarizes its own slice; no episode contains both.
        assert all(
            not ("alpha" in e.summary and "beta" in e.summary)
            for e in episodes
        )


class TestMemoryOps:
    def test_decision_extracted_with_stable_key(self):
        ops = extractor.propose_memory_ops(
            [_event(1, "user", "we'll use PostgreSQL for the database")]
        )
        decisions = [op for op in ops if op.type == "decision"]
        assert decisions and decisions[0].key == "database"
        assert "PostgreSQL" in decisions[0].value

    def test_constraint_extracted(self):
        ops = extractor.propose_memory_ops(
            [_event(1, "user", "don't change the existing UI")]
        )
        assert any(op.type == "constraint" for op in ops)

    def test_preference_extracted(self):
        ops = extractor.propose_memory_ops(
            [_event(1, "user", "I prefer tabs over spaces")]
        )
        assert any(op.type == "preference" for op in ops)

    def test_goal_extracted(self):
        ops = extractor.propose_memory_ops(
            [_event(1, "user", "we need to ship by Friday")]
        )
        assert any(op.type == "goal" for op in ops)

    def test_low_value_chatter_ignored(self):
        assert extractor.propose_memory_ops([_event(1, "user", "thanks")]) == []
        assert extractor.propose_memory_ops([_event(1, "user", "ok")]) == []

    def test_assistant_prose_is_not_mined(self):
        ops = extractor.propose_memory_ops(
            [_event(1, "assistant", "we'll use PostgreSQL for the database")]
        )
        assert ops == []

    def test_decision_without_known_key_is_dropped(self):
        # "switch to X" with no recognizable concept noun -> no guessy key.
        ops = extractor.propose_memory_ops(
            [_event(1, "user", "let's switch to zebra mode")]
        )
        assert [op for op in ops if op.type == "decision"] == []


class TestWorkingMemory:
    def test_update_folds_goal_questions_and_ops(self):
        ops = extractor.propose_memory_ops(
            [_event(1, "user", "don't change the existing UI")]
        )
        wm = extractor.update_working_memory(
            None,
            conversation_id="c",
            user_prompt=(
                "We need to fix pagination. What should the empty state show?"
            ),
            assistant_text="I'll mock the API response.",
            status="done",
            ops=ops,
            now="t",
        )
        assert wm.current_task.startswith("We need to fix pagination")
        assert wm.current_goal == "fix pagination"
        assert wm.constraints
        assert wm.open_questions
        assert wm.current_status == "done"

    def test_update_is_bounded_and_deduped(self):
        previous = WorkingMemory(
            conversation_id="c", decisions=["keep this"]
        )
        wm = extractor.update_working_memory(
            previous,
            conversation_id="c",
            user_prompt="",
            now="t",
        )
        assert wm.decisions == ["keep this"]
