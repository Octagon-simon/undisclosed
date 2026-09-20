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

"""Project layer, project resolution and scope-aware ranking (§3, §14, §17)."""

from __future__ import annotations

from app.memory import LocalMemoryStore
from app.memory.events import ConversationEvent, ProjectMemory
from app.memory.hybrid import engine
from app.memory.hybrid.project import ProjectStore
from app.memory.hybrid.resolver import CONFIDENCE_FLOOR, resolve
from app.memory.hybrid.schema import MemoryOp

IDS = {
    "user_key": "user_42",
    "space_id": "space_test",
    "project_id": "project_test",
    "conversation_id": "project_test",
}


def _write_project(
    store: LocalMemoryStore, user_key: str, space_id: str, project_id: str, name: str
) -> None:
    """Mirror what MemoryService writes: a per-project project.json."""

    store.write_project(
        user_key,
        ProjectMemory(
            project_id=project_id,
            space_id=space_id,
            name=name,
            created_at="t",
            updated_at="t",
        ),
    )


class TestProjectStore:
    def test_ensure_is_idempotent_and_keeps_created_at(self, store):
        ps = ProjectStore(store)
        first = ps.ensure(
            "u", project_id="p1", space_id="s1", name="Mac app", now="t1"
        )
        assert first is not None and first.created_at == "t1"
        second = ps.ensure(
            "u", project_id="p1", space_id="s1", name="Mac app", now="t2"
        )
        assert second.created_at == "t1"
        assert second.updated_at == "t2"
        assert len(ps.read_projects("u")) == 1

    def test_discover_unions_walk_with_registry(self, store):
        # p1 exists only as a project dir (predates the registry).
        _write_project(store, "u", "s1", "p1", "Mac app")
        ps = ProjectStore(store)
        ps.ensure(
            "u",
            project_id="p2",
            space_id="s2",
            name="Web app",
            description="browser thing",
            now="t",
        )
        found = {p.id: p for p in ps.discover("u")}
        assert found["p1"].name == "Mac app"  # name read from project.json
        assert found["p2"].description == "browser thing"
        assert found["p2"].space_id == "s2"

    def test_conversation_link_roundtrip_and_idempotent(self, store):
        ps = ProjectStore(store)
        ps.ensure("u", project_id="p1", space_id="s1", name="Mac app", now="t")
        ps.link_conversation(
            "u",
            conversation_id="c1",
            project_id="p1",
            space_id="s1",
            title="Kickoff",
            now="t",
        )
        ref = ps.project_for_conversation("u", "c1")
        assert ref is not None
        assert (ref.project_id, ref.space_id, ref.title) == ("p1", "s1", "Kickoff")
        assert [c.id for c in ps.conversations_for_project("u", "p1")] == ["c1"]
        ps.link_conversation(
            "u", conversation_id="c1", project_id="p1", space_id="s1", now="t2"
        )
        assert len(ps.read_conversations("u")) == 1

    def test_archived_project_is_discoverable_but_not_active(self, store):
        ps = ProjectStore(store)
        ps.ensure("u", project_id="p1", space_id="s1", name="Mac app", now="t")
        ps.set_status("u", "p1", "archived", now="t2")
        assert ps.active_projects("u") == []
        assert [p.id for p in ps.discover("u")] == ["p1"]


class TestProjectResolver:
    def _ps(self, store, projects):
        ps = ProjectStore(store)
        for space_id, project_id, name, description in projects:
            _write_project(store, "u", space_id, project_id, name)
            if description:
                ps.ensure(
                    "u",
                    project_id=project_id,
                    space_id=space_id,
                    name=name,
                    description=description,
                    now="t",
                )
        return ps

    def test_explicit_id_wins(self, store):
        ps = self._ps(store, [("s1", "mac", "Mac app", "")])
        r = resolve(ps, "u", explicit_project_id="mac", query="anything")
        assert r.project_id == "mac"
        assert r.reason == "explicit"
        assert r.confidence == 1.0

    def test_conversation_link_beats_name_match(self, store):
        ps = self._ps(
            store, [("s1", "mac", "Mac app", ""), ("s2", "web", "Web app", "")]
        )
        ps.link_conversation(
            "u", conversation_id="c1", project_id="web", space_id="s2", now="t"
        )
        r = resolve(ps, "u", conversation_id="c1", query="continue the Mac app")
        assert r.project_id == "web"
        assert r.reason == "conversation_link"
        assert r.confidence == 0.9

    def test_project_named_in_request_resolves(self, store):
        ps = self._ps(
            store,
            [("s1", "chefly", "CheflyMenu", ""), ("s2", "web", "Web app", "")],
        )
        r = resolve(ps, "u", query="continue working on CheflyMenu")
        assert r.confident
        assert r.project_id == "chefly"
        assert r.reason == "name_match"

    def test_unrelated_query_does_not_force_a_project(self, store):
        ps = self._ps(
            store,
            [("s1", "mac", "Mac app", ""), ("s2", "web", "Web app", "")],
        )
        r = resolve(ps, "u", query="what is the weather like today")
        assert not r.confident
        assert r.project_id == ""

    def test_single_active_project_is_the_fallback(self, store):
        ps = self._ps(store, [("s1", "mac", "Mac app", "")])
        r = resolve(ps, "u", query="how are things going")
        assert r.reason == "only_active_project"
        assert r.project_id == "mac"
        assert r.confidence == CONFIDENCE_FLOOR

    def test_resolve_links_the_conversation(self, store):
        ps = self._ps(store, [("s1", "chefly", "CheflyMenu", "")])
        resolve(ps, "u", conversation_id="c9", query="continue CheflyMenu")
        ref = ps.project_for_conversation("u", "c9")
        assert ref is not None and ref.project_id == "chefly"

    def test_missing_projects_is_not_an_error(self, store):
        r = resolve(ProjectStore(store), "u", query="anything")
        assert r.project_id == ""
        assert r.reason in {"no_projects", "no_query"}


class TestScopeAwareRanking:
    """§17: current-project memory must outrank an unrelated project's record."""

    def _seed(self, hybrid, *, space_id, project_id, value):
        hybrid.apply_ops(
            IDS["user_key"],
            space_id,
            project_id,
            [
                MemoryOp(
                    op="UPSERT",
                    type="decision",
                    key="database",
                    value=value,
                    source_message_ids=["m1"],
                )
            ],
            conversation_id=project_id,
            now="t9",
            scope_type="project",
            scope_id=project_id,
        )

    def test_current_project_ranks_above_other_project(self, hybrid, ids):
        self._seed(
            hybrid,
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            value="PostgreSQL",
        )
        self._seed(
            hybrid, space_id="space_other", project_id="project_other", value="MongoDB"
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
        texts = [m.text for m in result.active_memories]
        assert texts.index("database = PostgreSQL") < texts.index(
            "database = MongoDB"
        )
        top = result.active_memories[0]
        assert top.scores["project_match"] == 1.0


class TestEngineProjectResolution:
    def test_diagnostics_report_name_match(self, hybrid, ids):
        _write_project(
            hybrid.base, ids["user_key"], ids["space_id"], "chefly", "CheflyMenu"
        )
        hybrid.base.append_conversation(
            ids["user_key"],
            ids["space_id"],
            ids["project_id"],
            ConversationEvent(
                event_id="evt_1",
                run_id="run1",
                timestamp="t",
                role="user",
                content="we should pick a database",
                source="chat",
                visibility="context",
                hash="sha256:x",
            ),
        )
        result, _ = engine.retrieve(
            hybrid,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
            query="what did we decide about the CheflyMenu database",
            token_budget=4000,
        )
        resolution = result.diagnostics["project_resolution"]
        assert resolution["reason"] == "name_match"
        assert resolution["project_id"] == "chefly"

    def test_explicit_project_id_is_reported(self, hybrid, ids):
        result, _ = engine.retrieve(
            hybrid,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
            query="what database did we decide on",
            token_budget=4000,
            explicit_project_id="project_test",
        )
        assert result.diagnostics["project_resolution"]["reason"] == "explicit"


class TestEvidenceEscalation:
    def test_targeted_query_with_no_evidence_escalates_once(self, hybrid, ids):
        hybrid.base.append_conversation(
            ids["user_key"],
            ids["space_id"],
            ids["project_id"],
            ConversationEvent(
                event_id="evt_1",
                run_id="run1",
                timestamp="t",
                role="user",
                content="let's talk about the weather",
                source="chat",
                visibility="context",
                hash="sha256:x",
            ),
        )
        result, _ = engine.retrieve(
            hybrid,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
            query="what was the exact commit hash we used",
            token_budget=4000,
        )
        assert result.diagnostics["escalated"] is True
        assert result.plan.use_exact is True
        assert result.evidence_found == "none"


class TestRunEndProjectBookkeeping:
    def test_process_run_end_registers_and_links_project(self, hybrid, ids):
        hybrid.base.append_conversation(
            ids["user_key"],
            ids["space_id"],
            ids["project_id"],
            ConversationEvent(
                event_id="evt_1",
                run_id="run1",
                timestamp="t",
                role="user",
                content="we'll use PostgreSQL for the database",
                source="chat",
                visibility="context",
                hash="sha256:x",
            ),
        )
        engine.process_run_end(
            hybrid,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
        )
        ps = ProjectStore(hybrid.base)
        assert ps.get(ids["user_key"], ids["project_id"]) is not None
        ref = ps.project_for_conversation(
            ids["user_key"], ids["conversation_id"]
        )
        assert ref is not None and ref.project_id == ids["project_id"]
