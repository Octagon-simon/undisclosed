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

"""End-to-end engine tests: retrieval lanes, run-end pipeline, observability."""

from __future__ import annotations

from app.memory import LocalMemoryStore
from app.memory.events import ConversationEvent
from app.memory.hybrid import engine, vector
from app.memory.hybrid.schema import Episode

IDS = {
    "user_key": "user_42",
    "space_id": "space_test",
    "project_id": "project_test",
    "conversation_id": "project_test",
}


def _append_run(
    store: LocalMemoryStore, run_idx: int, user: str, assistant: str
) -> None:
    for role, content in (("user", user), ("assistant", assistant)):
        store.append_conversation(
            IDS["user_key"],
            IDS["space_id"],
            IDS["project_id"],
            ConversationEvent(
                event_id=f"evt_{run_idx}_{role}",
                run_id=f"run{run_idx}",
                timestamp="t",
                role=role,  # type: ignore[arg-type]
                content=content,
                source="chat",
                visibility="context",
                hash="sha256:x",
            ),
        )


class TestRunEndPipeline:
    def test_builds_episodes_and_structured_memory(self, hybrid, ids):
        _append_run(hybrid.base, 1, "we'll use MongoDB for the database", "Noted.")
        _append_run(hybrid.base, 2, "add an index on the users table", "Done.")
        _append_run(
            hybrid.base, 3, "we'll use PostgreSQL for the database", "Noted."
        )
        engine.process_run_end(
            hybrid,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
            budget_tokens=5,
        )
        assert hybrid.read_episodes(
            ids["user_key"], ids["space_id"], ids["project_id"]
        )
        assert hybrid.read_covered_through_turn(
            ids["user_key"], ids["space_id"], ids["project_id"]
        ) > 0
        active = hybrid.read_active_memories(
            ids["user_key"], ids["space_id"], ids["project_id"]
        )
        assert any(m.key == "database" for m in active)

    def test_changed_decision_supersedes(self, hybrid, ids):
        _append_run(hybrid.base, 1, "we'll use MongoDB for the database", "Ok.")
        engine.process_run_end(
            hybrid, **{k: ids[k] for k in ("user_key", "space_id", "project_id")},
            conversation_id=ids["conversation_id"], budget_tokens=5,
        )
        _append_run(
            hybrid.base, 2, "we'll use PostgreSQL for the database", "Ok."
        )
        engine.process_run_end(
            hybrid, **{k: ids[k] for k in ("user_key", "space_id", "project_id")},
            conversation_id=ids["conversation_id"], budget_tokens=5,
        )
        active = hybrid.read_active_memories(
            ids["user_key"], ids["space_id"], ids["project_id"]
        )
        superseded = hybrid.read_memories(
            ids["user_key"], ids["space_id"], ids["project_id"],
            status="superseded",
        )
        assert [m.value for m in active] == ["PostgreSQL for the database"]
        assert [m.value for m in superseded] == ["MongoDB for the database"]

    def test_working_memory_written(self, hybrid, ids):
        _append_run(hybrid.base, 1, "we need to fix pagination", "On it.")
        engine.process_run_end(
            hybrid, **{k: ids[k] for k in ("user_key", "space_id", "project_id")},
            conversation_id=ids["conversation_id"], budget_tokens=5,
        )
        wm = hybrid.read_working_memory(
            ids["user_key"], ids["space_id"], ids["project_id"]
        )
        assert wm is not None
        assert wm.current_task == "we need to fix pagination"


class TestRetrieval:
    def test_exact_query_returns_verbatim_evidence(self, hybrid, ids):
        _append_run(
            hybrid.base, 1, "we'll use PostgreSQL for the database", "Noted."
        )
        context = engine.build_context(
            hybrid,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
            query="what exact database did we settle on",
            token_budget=4000,
        )
        assert "exact_historical_evidence" in context
        assert "Prefer this verbatim evidence" in context
        assert "PostgreSQL" in context

    def test_continuation_uses_recent_only(self, hybrid, ids):
        _append_run(hybrid.base, 1, "design the authentication flow", "JWT.")
        _append_run(hybrid.base, 2, "add refresh tokens", "Done.")
        context = engine.build_context(
            hybrid,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
            query="continue",
            token_budget=4000,
        )
        assert "recent_conversation" in context
        assert "Add refresh tokens" in context or "add refresh tokens" in context

    def test_no_evidence_reports_not_found(self, hybrid, ids):
        _append_run(hybrid.base, 1, "hello there", "hi")
        context = engine.build_context(
            hybrid,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
            query="what exact commit hash did I give you",
            token_budget=4000,
        )
        assert "could not be recovered" in context

    def test_semantic_episode_surfaces(self, hybrid, ids, monkeypatch):
        hybrid.append_episodes(
            ids["user_key"], ids["space_id"], ids["project_id"],
            [
                Episode(
                    id="ep_auth",
                    conversation_id="c",
                    start_turn=1,
                    end_turn=4,
                    title="Authentication architecture",
                    summary="JWT with refresh tokens and short expiry.",
                    source_message_ids=["m1"],
                    created_at="t",
                )
            ],
        )
        monkeypatch.setattr(
            vector, "query_episodes", lambda *a, **k: [("ep_auth", 0.92)]
        )
        result, _recent = engine.retrieve(
            hybrid,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
            query="what did we discuss about the authentication architecture",
            token_budget=4000,
        )
        assert [e.id for e in result.episodes] == ["ep_auth"]

    def test_service_wrapper_returns_tagged_block(self, hybrid, ids):
        from app.memory.service import _build_hybrid_context_section

        _append_run(hybrid.base, 1, "we'll use PostgreSQL for the database", "Ok.")
        engine.process_run_end(
            hybrid,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
            budget_tokens=5,
        )
        rendered = _build_hybrid_context_section(
            store=hybrid.base,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            query="what database are we using",
            token_budget=4000,
        )
        assert rendered is not None
        assert rendered.startswith("<memory_rules>")
        assert "active_memory" in rendered
        assert "database = PostgreSQL" in rendered
        assert "recent_conversation" in rendered

    def test_durable_context_uses_hybrid_when_enabled(self, hybrid, ids, monkeypatch):
        from types import SimpleNamespace

        from app.memory import service as memory_service

        monkeypatch.setattr(memory_service.hybrid_config, "enabled", lambda: True)
        _append_run(hybrid.base, 1, "we'll use PostgreSQL for the database", "Ok.")
        engine.process_run_end(
            hybrid,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
            budget_tokens=5,
        )
        lock = SimpleNamespace(
            run_context=SimpleNamespace(
                user_id="42",
                email=None,
                space_id=ids["space_id"],
                project_id=ids["project_id"],
                run_id="run1",
            ),
            memory_service=SimpleNamespace(store=hybrid.base),
        )
        out = memory_service.build_durable_context_for_task_lock(
            lock,
            mode="single_agent",
            current_user_prompt="what database are we using",
            token_budget=4000,
            include_semantic=False,
        )
        assert out is not None
        assert "active_memory" in out
        assert "database = PostgreSQL" in out

    def test_toolkit_recall_history_uses_hybrid(self, hybrid, ids):
        from app.agent.toolkit.memory_toolkit import MemoryToolkit

        _append_run(hybrid.base, 1, "what port should we use", "Use port 8080.")
        toolkit = MemoryToolkit(
            api_task_id=ids["project_id"],
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            store=hybrid.base,
        )
        out = toolkit.recall_history("what exact port did we settle on")
        assert "8080" in out

    def test_toolkit_recall_history_reports_absence(self, hybrid, ids):
        from app.agent.toolkit.memory_toolkit import MemoryToolkit

        _append_run(hybrid.base, 1, "hello", "hi")
        toolkit = MemoryToolkit(
            api_task_id=ids["project_id"],
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            store=hybrid.base,
        )
        out = toolkit.recall_history("what exact commit hash did i give you")
        assert "No relevant earlier history" in out or "could not" in out.lower()

    def test_retrieval_log_is_written(self, hybrid, ids):
        _append_run(hybrid.base, 1, "design auth", "JWT.")
        engine.build_context(
            hybrid,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
            query="what did we decide about auth",
            token_budget=4000,
        )
        from app.memory.local_store import read_jsonl_file

        log_path = (
            hybrid.base.project_path(
                ids["user_key"], ids["space_id"], ids["project_id"]
            )
            / "retrieval_log.jsonl"
        )
        rows = read_jsonl_file(log_path)
        assert rows
        assert "evidence_found" in rows[-1]


class TestScopeRouting:
    """Scope decides *where* an op lands; the mutation gate still owns *whether* (§2, §23)."""

    def _upsert(self, value, *, key="database", type_="decision"):
        from app.memory.hybrid.schema import MemoryOp

        return MemoryOp(
            op="UPSERT",
            type=type_,
            key=key,
            value=value,
            source_message_ids=["m1"],
        )

    def test_ops_are_routed_to_their_scope_store(self, hybrid, ids):
        from app.memory.hybrid.scope import GlobalMemoryStore

        ops = [
            self._upsert("PostgreSQL"),
            self._upsert("concise commits", key="commit_style", type_="preference"),
            self._upsert("SQLite for this prototype", type_="fact"),
        ]
        counts = engine._apply_ops_by_scope(
            hybrid,
            ops,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
            now="t1",
        )
        assert counts == {"global": 1, "conversation": 1, "project": 1}

        project = hybrid.read_active_memories(
            ids["user_key"], ids["space_id"], ids["project_id"]
        )
        by_value = {m.value: m for m in project}
        assert by_value["PostgreSQL"].scope_type == "project"
        assert by_value["SQLite for this prototype"].scope_type == "conversation"

        at_root = GlobalMemoryStore(hybrid.base).read_active_memories(
            ids["user_key"], ids["space_id"], ids["project_id"]
        )
        assert [m.value for m in at_root] == ["concise commits"]
        assert at_root[0].user_id == ids["user_key"]


class TestCrossSessionRetrieval:
    def _seed(self, hybrid, ids, *, space_id, project_id, value, key="database"):
        from app.memory.hybrid.schema import MemoryOp

        hybrid.apply_ops(
            ids["user_key"],
            space_id,
            project_id,
            [
                MemoryOp(
                    op="UPSERT",
                    type="decision",
                    key=key,
                    value=value,
                    source_message_ids=["m1"],
                )
            ],
            conversation_id=project_id,
            now="t9",
            scope_type="project",
            scope_id=project_id,
        )

    def test_memory_from_another_project_is_retrieved(self, hybrid, ids):
        self._seed(
            hybrid,
            ids,
            space_id="space_other",
            project_id="project_other",
            value="PostgreSQL",
        )
        result, _ = engine.retrieve(
            hybrid,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
            query="what database did we decide on",
            token_budget=4000,
        )
        hits = [m for m in result.active_memories if m.text == "database = PostgreSQL"]
        assert hits, "cross-session hit should surface"
        assert hits[0].origin_project_id == "project_other"
        assert hits[0].scope == "project"

    def test_global_preference_is_retrieved_from_a_new_thread(self, hybrid, ids):
        from app.memory.hybrid.scope import GlobalMemoryStore

        GlobalMemoryStore(hybrid.base).apply_ops(
            ids["user_key"],
            ids["space_id"],
            ids["project_id"],
            [
                # Build via the engine helper so scope stamping matches the write path.
            ],
            conversation_id=ids["conversation_id"],
            now="t1",
        ) if False else None
        from app.memory.hybrid.schema import MemoryOp

        GlobalMemoryStore(hybrid.base).apply_ops(
            ids["user_key"],
            ids["space_id"],
            ids["project_id"],
            [
                MemoryOp(
                    op="UPSERT",
                    type="preference",
                    key="commit_style",
                    value="concise commit messages",
                    source_message_ids=["m1"],
                )
            ],
            conversation_id=ids["conversation_id"],
            now="t1",
            scope_type="global",
            scope_id=ids["user_key"],
            user_id=ids["user_key"],
        )
        result, _ = engine.retrieve(
            hybrid,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
            query="what is my commit message preference",
            token_budget=4000,
        )
        hits = [
            m
            for m in result.active_memories
            if m.text == "commit_style = concise commit messages"
        ]
        assert hits
        assert hits[0].scope == "global"
        assert hits[0].origin_project_id == ""

    def test_continuation_does_not_widen_cross_session(self, hybrid, ids):
        self._seed(
            hybrid,
            ids,
            space_id="space_other",
            project_id="project_other",
            value="PostgreSQL",
        )
        result, _ = engine.retrieve(
            hybrid,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
            query="continue",
            token_budget=4000,
        )
        from app.memory.hybrid.schema import LEVEL_RECENT

        assert result.plan.level == LEVEL_RECENT
        assert result.diagnostics["cross_session_memories"] == []
        assert not any(
            m.text == "database = PostgreSQL" for m in result.active_memories
        )
