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

"""Rolling conversation summary tests.

The property that matters most: the merge is CUMULATIVE. Turn N's stored
summary is a summary of turns 1..N together, never a bag of independent
per-turn summaries.
"""

from __future__ import annotations

import json

from app.memory import (
    ConversationEvent,
    LocalMemoryStore,
    RollingSummary,
    TurnDigest,
    append_turn,
    build_turn_digest,
    render_md,
    rolling_summary as rs,
)


def _digest(run_id: str, user: str, did: str, status: str = "done") -> TurnDigest:
    return build_turn_digest(
        query_id=run_id,
        status=status,
        user_prompt=user,
        final_result=did,
        ts="2026-09-12T21:00:00Z",
    )


# ----- The cumulative invariant -----


class TestCumulativeInvariant:
    def test_merge_is_cumulative_not_per_turn(self):
        summary = RollingSummary(project_id="p1")
        summary = append_turn(summary, _digest("r1", "diagnose the bug", "Found it."))
        summary = append_turn(summary, _digest("r2", "implement", "Wrote the fix."))
        summary = append_turn(summary, _digest("r3", "add tests", "Added tests."))

        # Turn 3's document summarizes ALL turns, not just turn 3.
        assert summary.turn_count == 3
        assert [t.n for t in summary.turns] == [1, 2, 3]
        rendered = render_md(summary)
        assert "turns 1..3" in rendered
        assert "diagnose the bug" in rendered
        assert "implement" in rendered
        assert "add tests" in rendered

    def test_idempotent_append_per_query_id(self):
        summary = RollingSummary(project_id="p1")
        summary = append_turn(summary, _digest("r1", "first", "did first"))
        summary = append_turn(summary, _digest("r1", "first", "did first v2"))
        # Duplicate finalize of the same run does not double-append.
        assert summary.turn_count == 1
        assert summary.turns[0].did == "did first v2"

    def test_render_references_every_turn(self):
        summary = RollingSummary(project_id="p1")
        for i in range(1, 5):
            summary = append_turn(
                summary, _digest(f"r{i}", f"ask {i}", f"answer {i}")
            )
        rendered = render_md(summary)
        for i in range(1, 5):
            assert f"ask {i}" in rendered
            assert f"answer {i}" in rendered


# ----- Compaction -----


class TestCompaction:
    def test_compaction_folds_older_turns_into_rolling(self):
        summary = RollingSummary(project_id="p1")
        for i in range(1, 11):
            summary = append_turn(
                summary,
                _digest(f"r{i}", f"user {i} " + "x" * 200, f"did {i} " + "y" * 200),
            )
        compacted = rs.compact_if_over_budget(summary, budget=1500, keep=3)
        # Older turns are folded, NOT dropped.
        assert len(compacted.turns) == 3
        assert [t.n for t in compacted.turns] == [8, 9, 10]
        assert compacted.rolling
        # The folded turns survive inside the rolling narrative (the newest
        # folded turn is present even after the rolling cap trims the head).
        assert "Turn 7:" in compacted.rolling
        assert "did 7" in compacted.rolling
        # turn_count still reflects every turn seen.
        assert compacted.turn_count == 10

    def test_compaction_never_drops_below_keep(self):
        summary = RollingSummary(project_id="p1")
        for i in range(1, 6):
            summary = append_turn(
                summary, _digest(f"r{i}", "u" * 500, "d" * 500)
            )
        compacted = rs.compact_if_over_budget(summary, budget=1, keep=4)
        assert len(compacted.turns) == 4


# ----- Files / digest extraction -----


class TestDigestExtraction:
    def test_extract_touched_files_dedupes_and_bounds(self):
        events = [
            {"tool_name": "write_file", "arguments": {"file_path": "a.py"}},
            {"tool_name": "edit_file", "arguments": {"path": "a.py"}},
            {"tool_name": "shell", "arguments": {"command": "ls"}},
            {"tool_name": "apply_patch", "arguments": {"path": "b.ts"}},
            {"tool_name": "write_file", "arguments": {"file_path": ""}},
        ]
        files = rs.extract_touched_files(events)
        assert files == ["a.py", "b.ts"]

    def test_extract_touched_files_tolerates_junk(self):
        assert rs.extract_touched_files([None, "x", {"tool_name": None}]) == []

    def test_build_digest_uses_summary_over_final_result(self):
        digest = build_turn_digest(
            query_id="r1",
            status="done",
            user_prompt="q",
            final_result="long raw result. more words.",
            summary="Short distilled summary.",
        )
        assert digest.did == "Short distilled summary."

    def test_build_digest_failed_keeps_error(self):
        digest = build_turn_digest(
            query_id="r1",
            status="failed",
            user_prompt="q",
            final_result=None,
            summary=None,
            error="boom",
        )
        assert "boom" in digest.did


# ----- Backfill -----


class TestBackfill:
    def _event(self, run_id: str, role: str, content: str) -> ConversationEvent:
        return ConversationEvent(
            event_id=f"{run_id}-{role}",
            run_id=run_id,
            timestamp="t",
            role=role,  # type: ignore[arg-type]
            content=content,
            source="chat",
            visibility="context",
            hash="sha256:x",
        )

    def test_backfill_pairs_user_and_assistant(self):
        events = [
            self._event("r1", "user", "investigate the drop"),
            self._event("r1", "assistant", "Pricing change caused it."),
            self._event("r2", "user", "implement the fix"),
            self._event("r2", "assistant", "Applied the patch."),
        ]
        summary = rs.backfill_from_conversation(
            events, project_id="p1", updated_at="now"
        )
        assert summary.turn_count == 2
        assert summary.turns[0].user == "investigate the drop"
        assert summary.turns[1].user == "implement the fix"
        assert "Pricing change" in summary.turns[0].did

    def test_backfill_empty_is_empty(self):
        summary = rs.backfill_from_conversation([], project_id="p1")
        assert summary.turn_count == 0
        assert summary.turns == []


# ----- Store round-trip / recovery -----


class TestStoreRoundTrip:
    def _store(self, tmp_path) -> LocalMemoryStore:
        return LocalMemoryStore(root=tmp_path / "memory")

    def test_update_project_summary_json_roundtrip(self, tmp_path):
        store = self._store(tmp_path)
        digest = _digest("r1", "hello", "world")

        def _mutate(payload):
            current = RollingSummary.from_dict(payload) or RollingSummary(
                project_id="proj"
            )
            current = append_turn(current, digest)
            return current.to_dict()

        store.update_project_summary_json("user_1", "space", "proj", _mutate)
        loaded = RollingSummary.from_dict(
            store.read_project_summary_json("user_1", "space", "proj")
        )
        assert loaded is not None
        assert loaded.turn_count == 1
        assert loaded.turns[0].query_id == "r1"

    def test_load_recovers_from_corrupt_json(self, tmp_path):
        store = self._store(tmp_path)
        path = (
            store.project_path("user_1", "space", "proj") / "summary.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json", encoding="utf-8")
        assert store.read_project_summary_json("user_1", "space", "proj") is None
        assert rs.load(store, "user_1", "space", "proj") is None

    def test_rolling_summary_render_write_via_service_helpers(self, tmp_path):
        # A corrupt sidecar must not stop a fresh merge from rebuilding.
        store = self._store(tmp_path)
        path = store.project_path("u", "s", "p") / "summary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("garbage", encoding="utf-8")

        def _mutate(payload):
            current = RollingSummary.from_dict(payload) or RollingSummary(
                project_id="p"
            )
            current = append_turn(current, _digest("r1", "q", "a"))
            return current.to_dict()

        updated = store.update_project_summary_json("u", "s", "p", _mutate)
        assert updated is not None
        assert json.loads(path.read_text(encoding="utf-8"))["turn_count"] == 1
