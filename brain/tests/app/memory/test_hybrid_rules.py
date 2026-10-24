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

"""Persistent-rule tests: identity, always-on loading, detection, same-turn write."""

from __future__ import annotations

from types import SimpleNamespace

from app.memory.hybrid import assembler, rule_detect, rules
from app.memory.hybrid.schema import (
    LEVEL_EXACT,
    MemoryOp,
    RetrievalPlan,
    RetrievalResult,
    StructuredMemory,
)
from app.memory.hybrid.scope import GlobalMemoryStore
from app.memory.paths import canonical_user_id
from app.memory.service import record_turn_rules


def _constraint(
    value: str,
    key: str,
    *,
    severity: str = "hard",
    category: str = "licensing",
    scope_type: str = "project",
    scope_id: str = "project_test",
) -> MemoryOp:
    return MemoryOp(
        op="UPSERT",
        type="constraint",
        key=key,
        value=value,
        severity=severity,
        category=category,
        source_message_ids=["m1"],
        scope_type=scope_type,
        scope_id=scope_id,
    )


def _result() -> RetrievalResult:
    return RetrievalResult(plan=RetrievalPlan(level=LEVEL_EXACT, use_exact=True))


class TestSchemaRoundTrip:
    def test_legacy_record_defaults_to_soft_prompt(self):
        memory = StructuredMemory.from_dict(
            {
                "id": "mem_1",
                "conversation_id": "c",
                "type": "constraint",
                "key": "license_rule",
                "value": "put the license header on new files",
            }
        )
        assert memory is not None
        assert memory.severity == "soft"
        assert memory.enforcement == "prompt"
        assert memory.original_text == ""

    def test_rule_fields_round_trip(self):
        memory = StructuredMemory(
            id="mem_1",
            conversation_id="c",
            type="constraint",
            key="rule_license_header",
            value="not hardcode the license rule",
            severity="hard",
            category="licensing",
            original_text="Never hardcode the license rule.",
            last_confirmed_at="2026-10-23T00:00:00+00:00",
        )
        restored = StructuredMemory.from_dict(memory.to_dict())
        assert restored is not None
        assert restored.severity == "hard"
        assert restored.original_text == "Never hardcode the license rule."


class TestRuleIdentity:
    def test_two_constraints_coexist(self, hybrid, ids):
        hybrid.apply_ops(
            ids["user_key"],
            ids["space_id"],
            ids["project_id"],
            [
                _constraint("not hardcode the license rule", "rule_license"),
                _constraint("not use tabs for indentation", "rule_tabs"),
            ],
            conversation_id=ids["conversation_id"],
            now="2026-10-23T00:00:00+00:00",
        )
        rows = hybrid.read_active_memories(
            ids["user_key"], ids["space_id"], ids["project_id"]
        )
        assert len([r for r in rows if r.type == "constraint"]) == 2

    def test_repeat_promotes_and_bumps_confirmation(self, hybrid, ids):
        hybrid.apply_ops(
            ids["user_key"],
            ids["space_id"],
            ids["project_id"],
            [_constraint("not use tabs", "rule_tabs", severity="soft")],
            conversation_id=ids["conversation_id"],
            now="2026-10-23T00:00:00+00:00",
        )
        hybrid.apply_ops(
            ids["user_key"],
            ids["space_id"],
            ids["project_id"],
            [_constraint("not use tabs", "rule_tabs", severity="hard")],
            conversation_id=ids["conversation_id"],
            now="2026-10-24T00:00:00+00:00",
        )
        rows = hybrid.read_active_memories(
            ids["user_key"], ids["space_id"], ids["project_id"]
        )
        active = [r for r in rows if r.type == "constraint"]
        assert len(active) == 1
        assert active[0].severity == "hard"
        assert active[0].last_confirmed_at == "2026-10-24T00:00:00+00:00"

    def test_restated_rule_merges_into_legacy_key(self, hybrid, ids):
        hybrid.apply_ops(
            ids["user_key"],
            ids["space_id"],
            ids["project_id"],
            [_constraint("not hardcode the license rule", "constraint")],
            conversation_id=ids["conversation_id"],
            now="2026-10-23T00:00:00+00:00",
        )
        hybrid.apply_ops(
            ids["user_key"],
            ids["space_id"],
            ids["project_id"],
            [_constraint("not hardcode the license rule", "rule_hardcode_license")],
            conversation_id=ids["conversation_id"],
            now="2026-10-24T00:00:00+00:00",
        )
        rows = [
            r
            for r in hybrid.read_active_memories(
                ids["user_key"], ids["space_id"], ids["project_id"]
            )
            if r.type == "constraint"
        ]
        assert len(rows) == 1
        assert rows[0].key == "constraint"
        assert rows[0].last_confirmed_at == "2026-10-24T00:00:00+00:00"

    def test_invalid_severity_is_dropped(self, hybrid, ids):
        hybrid.apply_ops(
            ids["user_key"],
            ids["space_id"],
            ids["project_id"],
            [_constraint("not use tabs", "rule_tabs", severity="nonsense")],
            conversation_id=ids["conversation_id"],
            now="2026-10-23T00:00:00+00:00",
        )
        assert not hybrid.read_active_memories(
            ids["user_key"], ids["space_id"], ids["project_id"]
        )


class TestReadActiveRules:
    def test_project_and_global_rules_load_together(self, hybrid, ids):
        hybrid.apply_ops(
            ids["user_key"],
            ids["space_id"],
            ids["project_id"],
            [_constraint("not use tabs for indentation", "rule_tabs")],
            conversation_id=ids["conversation_id"],
            now="2026-10-23T00:00:00+00:00",
        )
        GlobalMemoryStore(hybrid.base).apply_ops(
            ids["user_key"],
            ids["space_id"],
            ids["project_id"],
            [
                _constraint(
                    "not hardcode the license rule into source",
                    "rule_license",
                    scope_type="global",
                    scope_id=ids["user_key"],
                )
            ],
            conversation_id=ids["conversation_id"],
            now="2026-10-23T00:00:00+00:00",
            scope_type="global",
            scope_id=ids["user_key"],
            user_id=ids["user_key"],
        )
        loaded = rules.read_active_rules(
            hybrid.base,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
        )
        assert {r.key for r in loaded} == {"rule_tabs", "rule_license"}

    def test_project_wins_same_key_over_global(self, hybrid, ids):
        GlobalMemoryStore(hybrid.base).apply_ops(
            ids["user_key"],
            ids["space_id"],
            ids["project_id"],
            [_constraint("global wording", "rule_same")],
            conversation_id=ids["conversation_id"],
            now="2026-10-23T00:00:00+00:00",
            scope_type="global",
            scope_id=ids["user_key"],
            user_id=ids["user_key"],
        )
        hybrid.apply_ops(
            ids["user_key"],
            ids["space_id"],
            ids["project_id"],
            [_constraint("project wording", "rule_same")],
            conversation_id=ids["conversation_id"],
            now="2026-10-23T00:00:00+00:00",
        )
        loaded = rules.read_active_rules(
            hybrid.base,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
        )
        assert [r.value for r in loaded] == ["project wording"]

    def test_other_conversation_rule_is_excluded(self, hybrid, ids):
        hybrid.apply_ops(
            ids["user_key"],
            ids["space_id"],
            ids["project_id"],
            [
                _constraint(
                    "not mention this elsewhere",
                    "rule_elsewhere",
                    scope_type="conversation",
                    scope_id="another_conversation",
                )
            ],
            conversation_id="another_conversation",
            now="2026-10-23T00:00:00+00:00",
            scope_type="conversation",
            scope_id="another_conversation",
        )
        assert (
            rules.read_active_rules(
                hybrid.base,
                user_key=ids["user_key"],
                space_id=ids["space_id"],
                project_id=ids["project_id"],
                conversation_id=ids["conversation_id"],
            )
            == []
        )

    def test_legacy_project_fragment_is_not_loaded(self, hybrid, ids):
        hybrid.apply_ops(
            ids["user_key"],
            ids["space_id"],
            ids["project_id"],
            [_constraint("not describe it", "constraint", severity="soft")],
            conversation_id=ids["conversation_id"],
            now="2026-10-23T00:00:00+00:00",
        )
        assert (
            rules.read_active_rules(
                hybrid.base,
                user_key=ids["user_key"],
                space_id=ids["space_id"],
                project_id=ids["project_id"],
                conversation_id=ids["conversation_id"],
            )
            == []
        )

    def test_hard_rule_is_loaded_whatever_its_length(self, hybrid, ids):
        hybrid.apply_ops(
            ids["user_key"],
            ids["space_id"],
            ids["project_id"],
            [_constraint("not use tabs", "rule_tabs", severity="hard")],
            conversation_id=ids["conversation_id"],
            now="2026-10-23T00:00:00+00:00",
        )
        loaded = rules.read_active_rules(
            hybrid.base,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
        )
        assert [r.key for r in loaded] == ["rule_tabs"]

    def test_nothing_is_cached_between_reads(self, hybrid, ids):
        before = rules.read_active_rules(
            hybrid.base,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
        )
        hybrid.apply_ops(
            ids["user_key"],
            ids["space_id"],
            ids["project_id"],
            [_constraint("not use tabs", "rule_tabs")],
            conversation_id=ids["conversation_id"],
            now="2026-10-23T00:00:00+00:00",
        )
        after = rules.read_active_rules(
            hybrid.base,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
        )
        assert before == []
        assert len(after) == 1


class TestRendering:
    def _memory(self, severity: str, value: str, category: str = "licensing"):
        return StructuredMemory(
            id=f"mem_{value[:4]}",
            conversation_id="c",
            type="constraint",
            key=f"rule_{value[:4]}",
            value=value,
            severity=severity,
            category=category,
            created_at="2026-10-23T00:00:00+00:00",
        )

    def test_empty_block_is_empty_string(self):
        assert rules.render_rules_block([], budget_chars=1000) == ""

    def test_block_lists_hard_and_soft(self):
        block = rules.render_rules_block(
            [
                self._memory("hard", "not hardcode the license rule"),
                self._memory("soft", "prefer tabs", "coding"),
            ],
            budget_chars=1000,
        )
        assert "<persistent_rules>" in block
        assert "[hard][licensing]" in block
        assert "[soft][coding]" in block

    def test_hard_rule_is_never_dropped_to_fit(self):
        block = rules.render_rules_block(
            [
                self._memory("hard", "not hardcode the license rule"),
                self._memory("soft", "x" * 400),
            ],
            budget_chars=10,
        )
        assert "not hardcode the license rule" in block

    def test_probe_fires_on_empty_or_every_tenth_turn(self):
        assert rules.should_probe([], 3) is True
        assert rules.should_probe([self._memory("soft", "tabs")], 3) is False
        assert rules.should_probe([self._memory("soft", "tabs")], 10) is True

    def test_assembler_emits_rules_and_recall_check(self):
        rendered = assembler.assemble(
            _result(),
            recent_events=[],
            token_budget=4000,
            rules=[self._memory("hard", "not hardcode the license rule")],
            recall_check=False,
        )
        assert "<persistent_rules>" in rendered
        assert "not hardcode the license rule" in rendered

    def test_assembler_empty_block_gets_probe(self):
        rendered = assembler.assemble(
            _result(),
            recent_events=[],
            token_budget=4000,
            rules=[],
            recall_check=True,
        )
        assert "<persistent_rules>" not in rendered
        assert "<recall_check>" in rendered
        assert "do not claim to remember a rule" in rendered


class TestDetect:
    def test_always_marker_is_a_hard_global_rule(self):
        candidates = rule_detect.detect(
            "Always remember the previously given license rule."
        )
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.severity == "hard"
        assert candidate.scope == "global"
        assert candidate.category == "licensing"
        assert candidate.key.startswith("rule_")

    def test_prohibition_is_detected(self):
        candidates = rule_detect.detect(
            "Don't hardcode the license header into new files."
        )
        assert candidates
        assert candidates[0].text.startswith("not ")
        assert candidates[0].severity == "hard"

    def test_one_time_is_conversation_and_soft(self):
        candidates = rule_detect.detect(
            "Just this once, don't add a copyright header."
        )
        assert len(candidates) == 1
        assert candidates[0].scope == "conversation"
        assert candidates[0].severity == "soft"

    def test_question_and_chatter_are_ignored(self):
        assert rule_detect.detect("Does it always fail?") == []
        assert rule_detect.detect("never mind") == []
        assert rule_detect.detect("don't worry about it") == []

    def test_same_rule_twice_same_key(self):
        first = rule_detect.detect("Never hardcode the license rule.")
        second = rule_detect.detect("Never hardcode the license rule.")
        assert first[0].key == second[0].key


class TestSameTurnWrite:
    def _lock(self, store):
        return SimpleNamespace(
            run_context=SimpleNamespace(
                user_id=0,
                email="user@example.com",
                space_id="space_test",
                project_id="project_test",
                run_id="run_test",
                task_id="task_test",
            ),
            memory_service=SimpleNamespace(store=store),
            conversation_history=[
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ],
        )

    def _loaded(self, store):
        return rules.read_active_rules(
            store,
            user_key=canonical_user_id(0, email="user@example.com"),
            space_id="space_test",
            project_id="project_test",
            conversation_id="project_test",
        )

    def test_rule_is_written_and_loadable_same_turn(self, store):
        lock = self._lock(store)
        written = record_turn_rules(
            lock, "Always remember the previously given license rule."
        )
        assert written == 1
        loaded = self._loaded(store)
        assert len(loaded) == 1
        assert "license rule" in loaded[0].value
        assert loaded[0].severity == "hard"

    def test_repeat_is_idempotent(self, store):
        lock = self._lock(store)
        prompt = "Always remember the previously given license rule."
        assert record_turn_rules(lock, prompt) == 1
        assert record_turn_rules(lock, prompt) == 1
        assert len(self._loaded(store)) == 1

    def test_context_contains_rule_on_the_same_turn(self, store):
        from app.memory.service import build_durable_context_for_task_lock

        lock = self._lock(store)
        record_turn_rules(
            lock, "Always remember the previously given license rule."
        )
        rendered = build_durable_context_for_task_lock(
            lock, mode="single_agent", current_user_prompt="unrelated question"
        )
        assert rendered is not None
        assert "<persistent_rules>" in rendered
        assert "license rule" in rendered

    def test_fallback_path_contains_rule_block(self, store, monkeypatch):
        from app.memory.hybrid import config as hybrid_config
        from app.memory.service import build_durable_context_for_task_lock

        monkeypatch.setattr(hybrid_config, "enabled", lambda: False)
        lock = self._lock(store)
        record_turn_rules(
            lock, "Always remember the previously given license rule."
        )
        rendered = build_durable_context_for_task_lock(
            lock, mode="single_agent", current_user_prompt="unrelated question"
        )
        assert rendered is not None
        assert "<persistent_rules>" in rendered
