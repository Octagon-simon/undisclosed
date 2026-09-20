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

"""Scope model tests (§2, §6, §23 of the cross-session feature)."""

from __future__ import annotations

from app.memory.hybrid.schema import MemoryOp
from app.memory.hybrid.scope import (
    GlobalMemoryStore,
    infer_scope,
    iter_user_projects,
    partition_by_scope,
    resolve_op_scope,
)


def _upsert(
    value: str,
    *,
    key: str = "database",
    type_: str = "decision",
    scope_type: str = "",
) -> MemoryOp:
    return MemoryOp(
        op="UPSERT",
        type=type_,
        key=key,
        value=value,
        source_message_ids=["m1"],
        scope_type=scope_type,
    )


class TestInferScope:
    def test_preference_type_defaults_to_global(self):
        assert infer_scope(_upsert("tabs", type_="preference")) == "global"

    def test_project_decision_defaults_to_project(self):
        assert infer_scope(_upsert("PostgreSQL")) == "project"

    def test_first_person_habit_is_global(self):
        assert (
            infer_scope(_upsert("I always use conventional commits", type_="fact"))
            == "global"
        )

    def test_explicit_temporary_phrase_is_conversation(self):
        assert (
            infer_scope(_upsert("SQLite for this prototype", type_="fact"))
            == "conversation"
        )

    def test_conversation_phrase_beats_global_phrase(self):
        # "just this once" must win over "I prefer", or a one-off becomes a
        # permanent global fact (§23 warning).
        op = _upsert("I prefer SQLite just this once", type_="preference")
        assert infer_scope(op) == "conversation"


class TestResolveOpScope:
    def test_project_scope_ids(self):
        scope, scope_id, user_id = resolve_op_scope(
            _upsert("PostgreSQL"),
            user_key="user_42",
            project_id="proj_a",
            conversation_id="proj_a",
        )
        assert (scope, scope_id, user_id) == ("project", "proj_a", "")

    def test_global_scope_carries_user_id(self):
        scope, scope_id, user_id = resolve_op_scope(
            _upsert("concise commits", type_="preference"),
            user_key="user_42",
            project_id="proj_a",
            conversation_id="proj_a",
        )
        assert (scope, scope_id, user_id) == ("global", "user_42", "user_42")

    def test_conversation_scope_uses_conversation_id(self):
        scope, scope_id, user_id = resolve_op_scope(
            _upsert("SQLite for this prototype", type_="fact"),
            user_key="user_42",
            project_id="proj_a",
            conversation_id="conv_7",
        )
        assert (scope, scope_id, user_id) == ("conversation", "conv_7", "")

    def test_explicit_scope_wins_over_inference(self):
        op = _upsert("PostgreSQL", scope_type="global")
        scope, _scope_id, user_id = resolve_op_scope(
            op,
            user_key="user_42",
            project_id="proj_a",
            conversation_id="proj_a",
        )
        assert scope == "global"
        assert user_id == "user_42"

    def test_unknown_explicit_scope_falls_back_to_inference(self):
        op = _upsert("PostgreSQL", scope_type="bogus")
        scope, _scope_id, _user_id = resolve_op_scope(
            op,
            user_key="user_42",
            project_id="proj_a",
            conversation_id="proj_a",
        )
        assert scope == "project"


class TestPartitionByScope:
    def test_groups_upserts_and_keeps_targeted_ops_in_project(self):
        ops = [
            _upsert("PostgreSQL"),
            _upsert("concise commits", type_="preference"),
            _upsert("SQLite for this prototype", type_="fact"),
            MemoryOp(op="DELETE", memory_id="mem_1", reason="stale"),
        ]
        buckets = partition_by_scope(
            ops,
            user_key="user_42",
            project_id="proj_a",
            conversation_id="conv_7",
        )
        # The DELETE addresses an existing record by id, so it can only be
        # resolved against the project store; it rides along with the UPSERTs.
        assert [o.op for o in buckets["project"]] == ["UPSERT", "DELETE"]
        assert [o.value for o in buckets["global"]] == ["concise commits"]
        assert [o.value for o in buckets["conversation"]] == [
            "SQLite for this prototype"
        ]


class TestGlobalStore:
    def test_global_memory_lands_at_user_root_not_project(self, store, ids):
        global_store = GlobalMemoryStore(store)
        global_store.apply_ops(
            ids["user_key"],
            ids["space_id"],
            ids["project_id"],
            [_upsert("concise commits", key="commit_style", type_="preference")],
            conversation_id=ids["conversation_id"],
            now="t1",
            scope_type="global",
            scope_id=ids["user_key"],
            user_id=ids["user_key"],
        )
        # Readable from the user root...
        at_root = global_store.read_active_memories(
            ids["user_key"], ids["space_id"], ids["project_id"]
        )
        assert [m.value for m in at_root] == ["concise commits"]
        # ...and absent from the project's own sidecar.
        from app.memory.hybrid.storage import HybridStore

        project_memories = HybridStore(store).read_active_memories(
            ids["user_key"], ids["space_id"], ids["project_id"]
        )
        assert project_memories == []


class TestIterUserProjects:
    def test_enumerates_spaces_and_projects(self, store, ids):
        for space, project in (("space_a", "proj_1"), ("space_b", "proj_2")):
            path = store.project_path(ids["user_key"], space, project)
            path.mkdir(parents=True, exist_ok=True)
        found = iter_user_projects(store, ids["user_key"])
        assert ("space_a", "proj_1") in found
        assert ("space_b", "proj_2") in found

    def test_missing_user_root_is_empty(self, store):
        assert iter_user_projects(store, "user_nobody") == []
