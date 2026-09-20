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

"""Hybrid store + versioned memory-op tests (§10-13)."""

from __future__ import annotations

from app.memory.hybrid.schema import Episode, MemoryOp, WorkingMemory


def _episode(ep_id: str, start: int, end: int) -> Episode:
    return Episode(
        id=ep_id,
        conversation_id="c",
        start_turn=start,
        end_turn=end,
        title="t",
        summary="s",
        source_message_ids=["m1", "m2"],
        created_at="now",
    )


class TestEpisodes:
    def test_append_dedupes_by_id_and_sorts(self, hybrid, ids):
        hybrid.append_episodes(
            ids["user_key"], ids["space_id"], ids["project_id"],
            [_episode("ep_b", 5, 8)],
        )
        result = hybrid.append_episodes(
            ids["user_key"], ids["space_id"], ids["project_id"],
            [_episode("ep_a", 1, 4), _episode("ep_b", 5, 8)],
        )
        assert [e.id for e in result] == ["ep_a", "ep_b"]

    def test_read_missing_is_empty(self, hybrid, ids):
        assert hybrid.read_episodes(
            ids["user_key"], ids["space_id"], ids["project_id"]
        ) == []


class TestMemoryOps:
    def _upsert(self, value: str, key: str = "database") -> MemoryOp:
        return MemoryOp(
            op="UPSERT",
            type="decision",
            key=key,
            value=value,
            source_message_ids=["m1"],
        )

    def test_upsert_creates_version_one(self, hybrid, ids):
        hybrid.apply_ops(
            ids["user_key"], ids["space_id"], ids["project_id"],
            [self._upsert("MongoDB")],
            conversation_id="c", now="t1",
        )
        active = hybrid.read_active_memories(
            ids["user_key"], ids["space_id"], ids["project_id"]
        )
        assert len(active) == 1
        assert active[0].value == "MongoDB"
        assert active[0].version == 1
        assert active[0].key == "database"

    def test_changed_value_supersedes_and_bumps_version(self, hybrid, ids):
        u = ids["user_key"], ids["space_id"], ids["project_id"]
        hybrid.apply_ops(*u, [self._upsert("MongoDB")], conversation_id="c", now="t1")
        hybrid.apply_ops(
            *u, [self._upsert("PostgreSQL")], conversation_id="c", now="t2"
        )
        active = hybrid.read_active_memories(*u)
        superseded = hybrid.read_memories(*u, status="superseded")
        assert [m.value for m in active] == ["PostgreSQL"]
        assert active[0].version == 2
        assert [m.value for m in superseded] == ["MongoDB"]

    def test_identical_value_is_idempotent(self, hybrid, ids):
        u = ids["user_key"], ids["space_id"], ids["project_id"]
        hybrid.apply_ops(*u, [self._upsert("MongoDB")], conversation_id="c", now="t1")
        hybrid.apply_ops(*u, [self._upsert("MongoDB")], conversation_id="c", now="t2")
        all_memories = hybrid.read_memories(*u)
        assert len(all_memories) == 1
        assert all_memories[0].version == 1

    def test_alias_keys_collapse_to_one_identity(self, hybrid, ids):
        u = ids["user_key"], ids["space_id"], ids["project_id"]
        hybrid.apply_ops(*u, [self._upsert("MongoDB", key="db")],
                         conversation_id="c", now="t1")
        hybrid.apply_ops(*u, [self._upsert("PostgreSQL", key="database")],
                         conversation_id="c", now="t2")
        # "db" and "database" canonicalize to the same identity.
        assert len(hybrid.read_active_memories(*u)) == 1
        assert len(hybrid.read_memories(*u, status="superseded")) == 1

    def test_delete_removes_from_active(self, hybrid, ids):
        u = ids["user_key"], ids["space_id"], ids["project_id"]
        hybrid.apply_ops(*u, [self._upsert("MongoDB")], conversation_id="c", now="t1")
        memory_id = hybrid.read_active_memories(*u)[0].id
        hybrid.apply_ops(
            *u,
            [MemoryOp(op="DELETE", memory_id=memory_id)],
            conversation_id="c",
            now="t2",
        )
        assert hybrid.read_active_memories(*u) == []
        assert [m.status for m in hybrid.read_memories(*u)] == ["deleted"]

    def test_merge_extends_value(self, hybrid, ids):
        u = ids["user_key"], ids["space_id"], ids["project_id"]
        hybrid.apply_ops(*u, [self._upsert("45s")], conversation_id="c", now="t1")
        memory_id = hybrid.read_active_memories(*u)[0].id
        hybrid.apply_ops(
            *u,
            [MemoryOp(op="MERGE", memory_id=memory_id, value="with 3 retries")],
            conversation_id="c",
            now="t2",
        )
        active = hybrid.read_active_memories(*u)
        assert len(active) == 1
        assert "45s" in active[0].value and "3 retries" in active[0].value

    def test_unknown_target_is_ignored(self, hybrid, ids):
        u = ids["user_key"], ids["space_id"], ids["project_id"]
        result = hybrid.apply_ops(
            *u,
            [MemoryOp(op="SUPERSEDE", memory_id="mem_missing")],
            conversation_id="c",
            now="t1",
        )
        assert result == []

    def test_unknown_type_op_is_dropped(self, hybrid, ids):
        u = ids["user_key"], ids["space_id"], ids["project_id"]
        hybrid.apply_ops(
            *u,
            [MemoryOp(op="UPSERT", type="bogus", key="x", value="y")],
            conversation_id="c",
            now="t1",
        )
        assert hybrid.read_memories(*u) == []


class TestMemoryScope:
    """Scope stamping on UPSERT (§2, §6, §23 of the cross-session feature)."""

    def _upsert(self, value: str, key: str = "database") -> MemoryOp:
        return MemoryOp(
            op="UPSERT",
            type="decision",
            key=key,
            value=value,
            importance=0.9,
            source_message_ids=["m1"],
        )

    def test_default_scope_is_project(self, hybrid, ids):
        u = ids["user_key"], ids["space_id"], ids["project_id"]
        hybrid.apply_ops(*u, [self._upsert("PostgreSQL")],
                         conversation_id="c", now="t1")
        memory = hybrid.read_active_memories(*u)[0]
        assert memory.scope_type == "project"
        assert memory.importance == 0.9

    def test_global_scope_is_stamped_with_user(self, hybrid, ids):
        u = ids["user_key"], ids["space_id"], ids["project_id"]
        hybrid.apply_ops(
            *u,
            [self._upsert("concise commits", key="commit_style")],
            conversation_id="c",
            now="t1",
            scope_type="global",
            scope_id="user_42",
            user_id="user_42",
        )
        memory = hybrid.read_active_memories(*u)[0]
        assert memory.scope_type == "global"
        assert memory.scope_id == "user_42"
        assert memory.user_id == "user_42"

    def test_scope_carries_into_the_next_version(self, hybrid, ids):
        u = ids["user_key"], ids["space_id"], ids["project_id"]
        hybrid.apply_ops(
            *u, [self._upsert("SQLite")],
            conversation_id="c", now="t1", scope_type="project",
            scope_id="proj_a", user_id="user_42",
        )
        hybrid.apply_ops(
            *u, [self._upsert("PostgreSQL")],
            conversation_id="c", now="t2", scope_type="project",
            scope_id="proj_a", user_id="user_42",
        )
        active = hybrid.read_active_memories(*u)[0]
        assert active.version == 2
        assert active.scope_id == "proj_a"
        assert active.user_id == "user_42"


class TestWorkingMemoryAndMeta:
    def test_working_memory_roundtrip(self, hybrid, ids):
        payload = WorkingMemory(
            conversation_id="c",
            current_task="fix pagination",
            decisions=["mock the API"],
            constraints=["do not change the UI"],
            updated_at="now",
        )
        hybrid.write_working_memory(
            ids["user_key"], ids["space_id"], ids["project_id"], payload
        )
        loaded = hybrid.read_working_memory(
            ids["user_key"], ids["space_id"], ids["project_id"]
        )
        assert loaded == payload

    def test_missing_working_memory_is_none(self, hybrid, ids):
        assert hybrid.read_working_memory(
            ids["user_key"], ids["space_id"], ids["project_id"]
        ) is None

    def test_coverage_watermark_roundtrip(self, hybrid, ids):
        assert hybrid.read_covered_through_turn(
            ids["user_key"], ids["space_id"], ids["project_id"]
        ) == 0
        hybrid.write_covered_through_turn(
            ids["user_key"], ids["space_id"], ids["project_id"], 12, now="t"
        )
        assert hybrid.read_covered_through_turn(
            ids["user_key"], ids["space_id"], ids["project_id"]
        ) == 12


class TestProvenanceGate:
    """§4/§41.8: a derived memory must retain source ids it can actually back up."""

    def _upsert(self, *, sources, key="database", value="PostgreSQL"):
        return MemoryOp(
            op="UPSERT",
            type="decision",
            key=key,
            value=value,
            source_message_ids=sources,
        )

    def _apply(self, hybrid, ids, op, *, valid):
        return hybrid.apply_ops(
            ids["user_key"],
            ids["space_id"],
            ids["project_id"],
            [op],
            conversation_id=ids["conversation_id"],
            now="t",
            valid_source_ids=valid,
        )

    def test_op_citing_an_unknown_message_is_dropped(self, hybrid, ids):
        self._apply(
            hybrid, ids, self._upsert(sources=["msg_invented"]),
            valid={"msg_1", "msg_2"},
        )
        assert (
            hybrid.read_active_memories(
                ids["user_key"], ids["space_id"], ids["project_id"]
            )
            == []
        )

    def test_op_with_no_sources_is_dropped_when_validating(self, hybrid, ids):
        self._apply(hybrid, ids, self._upsert(sources=[]), valid={"msg_1"})
        assert (
            hybrid.read_active_memories(
                ids["user_key"], ids["space_id"], ids["project_id"]
            )
            == []
        )

    def test_op_with_a_known_source_is_kept_with_provenance(self, hybrid, ids):
        self._apply(hybrid, ids, self._upsert(sources=["msg_1"]), valid={"msg_1"})
        active = hybrid.read_active_memories(
            ids["user_key"], ids["space_id"], ids["project_id"]
        )
        assert [m.value for m in active] == ["PostgreSQL"]
        assert active[0].source_message_ids == ["msg_1"]
