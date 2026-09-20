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

"""Vector index metadata, filtering and fail-soft behaviour (§5, §16, §30-31).

The autouse conftest fixture disables Chroma so no test touches the real tree;
these tests inject a fake collection instead and assert on the metadata the
durable records are indexed with (the part §16 filtering depends on).
"""

from __future__ import annotations

import json

import pytest

from app.memory.hybrid import engine, vector
from app.memory.hybrid.schema import Episode, MemoryOp, StructuredMemory


class _FakeCollection:
    def __init__(self) -> None:
        self.upserts: list[dict] = []
        self.deleted: list[list[str]] = []
        self.queries: list[dict] = []

    def upsert(self, *, ids, documents, metadatas):  # noqa: ANN001
        self.upserts.append(
            {"ids": ids, "documents": documents, "metadatas": metadatas}
        )

    def delete(self, *, ids):  # noqa: ANN001
        self.deleted.append(ids)

    def query(self, *, query_texts, n_results, where=None):  # noqa: ANN001
        self.queries.append({"where": where, "n": n_results})
        return {"ids": [["ep_1", "ep_2"]], "distances": [[0.0, 1.0]]}


@pytest.fixture
def fake(monkeypatch) -> _FakeCollection:
    coll = _FakeCollection()
    monkeypatch.setattr(vector, "_get_collection", lambda _name: coll)
    return coll


def _episode(**over) -> Episode:
    base = dict(
        id="ep_1",
        conversation_id="conv_1",
        start_turn=3,
        end_turn=9,
        title="Database choice",
        summary="Decided on PostgreSQL.",
        source_message_ids=["m1", "m2"],
        importance=0.8,
        created_at="t1",
    )
    base.update(over)
    return Episode(**base)


def _memory(**over) -> StructuredMemory:
    base = dict(
        id="mem_1",
        conversation_id="conv_1",
        type="decision",
        key="database",
        value="PostgreSQL",
        source_message_ids=["m1"],
        scope_type="project",
        scope_id="proj_1",
        importance=0.7,
        updated_at="t1",
    )
    base.update(over)
    return StructuredMemory(**base)


class TestEpisodeIndex:
    def test_metadata_carries_provenance_and_turn_range(self, fake):
        vector.index_episode("u", "s", "p", _episode(), "doc text")
        row = fake.upserts[0]
        assert row["ids"] == ["ep_1"]
        meta = row["metadatas"][0]
        assert meta["episode_id"] == "ep_1"
        assert meta["project"] == "p"
        assert meta["conversation_id"] == "conv_1"
        assert json.loads(meta["source_message_ids"]) == ["m1", "m2"]
        assert meta["source_message_count"] == 2
        assert (meta["start_turn"], meta["end_turn"]) == (3, 9)
        assert meta["importance"] == 0.8

    def test_empty_text_is_not_indexed(self, fake):
        vector.index_episode("u", "s", "p", _episode(title="", summary="", topic=""))
        assert fake.upserts == []

    def test_query_filters_to_user_and_project(self, fake):
        vector.query_episodes("u", "p", "database", k=3)
        where = fake.queries[-1]["where"]
        assert {"user": "u"} in where["$and"]
        assert {"project": "p"} in where["$and"]

    def test_query_without_project_filters_user_only(self, fake):
        vector.query_episodes("u", None, "database", k=3)
        assert fake.queries[-1]["where"] == {"user": "u"}

    def test_remove_deletes_by_id(self, fake):
        vector.remove_episode("ep_1")
        assert fake.deleted == [["ep_1"]]


class TestMemoryIndex:
    def test_metadata_carries_scope_and_sources(self, fake):
        vector.index_memory("u", "s", "p", "conv_1", _memory())
        meta = fake.upserts[0]["metadatas"][0]
        assert meta["memory_id"] == "mem_1"
        assert meta["scope_type"] == "project"
        assert meta["scope_id"] == "proj_1"
        assert meta["memory_type"] == "decision"
        assert meta["status"] == "active"
        assert json.loads(meta["source_message_ids"]) == ["m1"]
        assert meta["importance"] == 0.7

    def test_query_is_user_scoped_and_filterable(self, fake):
        vector.query_memories(
            "u", "database", k=5, project_id="p", scope_type="project"
        )
        where = fake.queries[-1]["where"]
        assert {"user": "u"} in where["$and"]
        assert {"project": "p"} in where["$and"]
        assert {"scope_type": "project"} in where["$and"]

    def test_empty_query_returns_nothing(self, fake):
        assert vector.query_memories("u", "   ") == []
        assert fake.queries == []


class _BrokenCollection:
    def upsert(self, **_kw):  # noqa: ANN003
        raise RuntimeError("chroma write failed")

    def delete(self, **_kw):  # noqa: ANN003
        raise RuntimeError("chroma delete failed")

    def query(self, **_kw):  # noqa: ANN003
        raise RuntimeError("chroma read failed")


class TestFailSoft:
    def test_helpers_noop_when_index_unavailable(self, monkeypatch):
        # No collection (chroma missing / disabled) -> silent no-op.
        monkeypatch.setattr(vector, "_get_collection", lambda _name: None)
        vector.index_episode("u", "s", "p", _episode(), "doc")
        vector.index_memory("u", "s", "p", "c", _memory())
        vector.remove_episode("ep_1")
        vector.remove_memory("mem_1")
        assert vector.query_episodes("u", "p", "q") == []
        assert vector.query_memories("u", "q") == []

    def test_collection_errors_are_swallowed(self, monkeypatch):
        # A live-but-failing collection must never break a turn.
        monkeypatch.setattr(vector, "_get_collection", lambda _name: _BrokenCollection())
        vector.index_episode("u", "s", "p", _episode(), "doc")
        vector.index_memory("u", "s", "p", "c", _memory())
        assert vector.query_episodes("u", "p", "q") == []
        assert vector.query_memories("u", "q") == []


class TestWritePathIndexesMemories:
    def test_applied_ops_are_indexed_with_provenance(self, hybrid, ids, fake):
        counts = engine._apply_ops_by_scope(
            hybrid,
            [
                MemoryOp(
                    op="UPSERT",
                    type="decision",
                    key="database",
                    value="PostgreSQL",
                    source_message_ids=["m1"],
                )
            ],
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
            now="t1",
        )
        assert counts == {"project": 1}
        assert fake.upserts, "the applied memory should be indexed"
        meta = fake.upserts[-1]["metadatas"][0]
        assert meta["scope_type"] == "project"
        assert meta["key"] == "database"
        assert json.loads(meta["source_message_ids"]) == ["m1"]
