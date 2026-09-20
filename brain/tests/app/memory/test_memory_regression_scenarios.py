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

"""§36 memory regression scenarios: the behaviours the spec calls out by name.

Each test is one of the scenario blocks in ``memory-cross-session-feature.md``
§36, written against the real engine + stores (not mocks) so it doubles as the
"evaluate memory quality with real conversations" suite §35/§41.19 asks for.
"""

from __future__ import annotations

from app.memory.events import ConversationEvent
from app.memory.hybrid import engine
from app.memory.hybrid.schema import MemoryOp
from app.memory.hybrid.scope import GlobalMemoryStore
from app.memory.hybrid.storage import HybridStore

IDS = {
    "user_key": "user_42",
    "space_id": "space_test",
    "project_id": "project_test",
    "conversation_id": "project_test",
}


def _append(
    hybrid: HybridStore,
    *,
    user=IDS["user_key"],
    space=IDS["space_id"],
    project=IDS["project_id"],
    event_id: str,
    run_id: str,
    role: str,
    content: str,
) -> None:
    hybrid.base.append_conversation(
        user,
        space,
        project,
        ConversationEvent(
            event_id=event_id,
            run_id=run_id,
            timestamp="t",
            role=role,  # type: ignore[arg-type]
            content=content,
            source="chat",
            visibility="context",
            hash="sha256:x",
        ),
    )


def _remember(
    hybrid: HybridStore,
    *,
    user=IDS["user_key"],
    space=IDS["space_id"],
    project=IDS["project_id"],
    key: str,
    value: str,
    type_: str = "decision",
) -> None:
    hybrid.apply_ops(
        user,
        space,
        project,
        [
            MemoryOp(
                op="UPSERT",
                type=type_,
                key=key,
                value=value,
                source_message_ids=["m1"],
            )
        ],
        conversation_id=project,
        now="t9",
        scope_type="project",
        scope_id=project,
    )


def _retrieve(hybrid: HybridStore, query: str, **over):
    kwargs = dict(
        user_key=IDS["user_key"],
        space_id=IDS["space_id"],
        project_id=IDS["project_id"],
        conversation_id=IDS["conversation_id"],
        query=query,
        token_budget=4000,
    )
    kwargs.update(over)
    return engine.retrieve(hybrid, **kwargs)


class TestContinuityAndCrossThread:
    def test_same_thread_continuation_uses_recent_not_history(self, hybrid, ids):
        _append(hybrid, event_id="e1", run_id="r1", role="user", content="we are building X")
        _append(hybrid, event_id="e2", run_id="r1", role="assistant", content="understood")
        result, recent = _retrieve(hybrid, "continue that work")
        from app.memory.hybrid.schema import LEVEL_RECENT

        assert result.plan.level == LEVEL_RECENT
        assert recent  # the thread's own messages carry the continuation
        assert result.messages == []  # no history search on a continuation

    def test_cross_thread_recall_returns_the_decision_with_provenance(self, hybrid, ids):
        _remember(
            hybrid,
            space="space_other",
            project="project_other",
            key="database",
            value="PostgreSQL",
        )
        result, _ = _retrieve(hybrid, "what database did we decide on")
        hits = [m for m in result.active_memories if m.text == "database = PostgreSQL"]
        assert hits
        assert hits[0].origin_project_id == "project_other"


class TestRestartAndExactRecall:
    def test_memory_survives_a_backend_restart(self, store):
        first = HybridStore(store)
        _remember(first, key="database", value="PostgreSQL")
        # "Restart": a brand-new store object over the same on-disk tree.
        second = HybridStore(store)
        result, _ = engine.retrieve(
            second,
            user_key=IDS["user_key"],
            space_id=IDS["space_id"],
            project_id=IDS["project_id"],
            conversation_id=IDS["conversation_id"],
            query="what database did we decide on",
            token_budget=4000,
        )
        assert any(
            m.text == "database = PostgreSQL" for m in result.active_memories
        )

    def test_exact_historical_value_escalates_to_raw_evidence(self, hybrid, ids):
        _append(
            hybrid,
            event_id="e1",
            run_id="r1",
            role="assistant",
            content="the commit hash is 2cea8201f0d94b7c",
        )
        result, _ = _retrieve(hybrid, "what was that exact commit hash we used")
        assert result.evidence_found == "exact"
        assert any("2cea8201f0d94b7c" in m.text for m in result.messages)

    def test_absent_exact_value_is_reported_as_not_found(self, hybrid, ids):
        _append(hybrid, event_id="e1", run_id="r1", role="user", content="hello there")
        result, _ = _retrieve(hybrid, "what was the exact commit hash we used")
        assert result.evidence_found == "none"


class TestSupersessionAndScopeIsolation:
    def test_changed_decision_supersedes_and_history_is_kept(self, hybrid, ids):
        _remember(hybrid, key="database", value="SQLite")
        _remember(hybrid, key="database", value="PostgreSQL")
        result, _ = _retrieve(hybrid, "what database did we decide on")
        active = [m.text for m in result.active_memories]
        superseded = [m.text for m in result.superseded_memories]
        assert "database = PostgreSQL" in active
        assert "database = SQLite" in superseded
        assert "database = SQLite" not in active

    def test_project_a_decision_outranks_project_b(self, hybrid, ids):
        _remember(hybrid, key="database", value="PostgreSQL")  # project A (current)
        _remember(
            hybrid,
            space="space_b",
            project="project_b",
            key="database",
            value="MongoDB",
        )
        result, _ = _retrieve(hybrid, "what database did we decide on")
        texts = [m.text for m in result.active_memories]
        assert texts.index("database = PostgreSQL") < texts.index("database = MongoDB")


class TestGlobalPreferenceAndNoise:
    def test_global_preference_applies_to_a_new_thread(self, hybrid, ids):
        GlobalMemoryStore(hybrid.base).apply_ops(
            IDS["user_key"],
            IDS["space_id"],
            IDS["project_id"],
            [
                MemoryOp(
                    op="UPSERT",
                    type="preference",
                    key="commit_style",
                    value="concise commit messages",
                    source_message_ids=["m1"],
                )
            ],
            conversation_id=IDS["conversation_id"],
            now="t1",
            scope_type="global",
            scope_id=IDS["user_key"],
            user_id=IDS["user_key"],
        )
        # A brand-new thread (different project) still sees the preference.
        result, _ = _retrieve(
            hybrid,
            "what is my commit message preference",
            project_id="project_new",
            conversation_id="project_new",
        )
        hits = [
            m
            for m in result.active_memories
            if m.text == "commit_style = concise commit messages"
        ]
        assert hits and hits[0].scope == "global"

    def test_unrelated_thread_does_not_receive_other_projects_memory(self, hybrid, ids):
        _remember(
            hybrid,
            space="space_other",
            project="project_other",
            key="database",
            value="PostgreSQL",
        )
        result, _ = _retrieve(hybrid, "what is the capital of France")
        assert not any(
            m.text == "database = PostgreSQL" for m in result.active_memories
        )
        assert result.diagnostics["cross_session_memories"] == []
