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

"""Live Chroma round-trip, restart durability and legacy-collection migration.

This is the test the default suite cannot be: ``conftest`` disables Chroma, so
``test_hybrid_vector`` only ever asserts against a *fake* collection. That
leaves one thing unproven -- that a document written through the real
``chromadb.PersistentClient`` (with the on-device MiniLM embedding function) is
actually readable again after the process drops every handle, i.e. after a Brain
restart (§20, §31).

These tests are opt-in because they spin up a real Chroma client and the
embedding model. They write to a throwaway ``tmp_path`` root (``vector._root``
is monkeypatched), so they never touch the live
``~/.undisclosed/memory/semantic`` tree.

Run with::

    UNDISCLOSED_LIVE_CHROMA=1 .venv/bin/python -m pytest \
        tests/app/memory/test_hybrid_vector_live.py -q
"""

from __future__ import annotations

import os

import pytest

from app.memory.hybrid import vector
from app.memory.hybrid.schema import Episode, StructuredMemory

pytestmark = pytest.mark.skipif(
    not os.environ.get("UNDISCLOSED_LIVE_CHROMA"),
    reason="set UNDISCLOSED_LIVE_CHROMA=1 to run the live Chroma tests",
)


@pytest.fixture
def live_root(tmp_path, monkeypatch):
    """A real Chroma root at a temp dir plus clean vector-module state.

    The autouse ``conftest`` fixture has already called ``vector.disable()``;
    ``reset()`` here re-arms the module and clears any cached collection so the
    next ``_get_collection`` opens against ``tmp_path`` instead of the real
    tree.
    """

    root = tmp_path / "semantic"
    root.mkdir()
    monkeypatch.setattr(vector, "_root", lambda: root)
    vector.reset()
    yield root
    vector.reset()


def _episode(**over) -> Episode:
    base = dict(
        id="ep_live",
        conversation_id="conv_live",
        start_turn=1,
        end_turn=4,
        title="Ledger datastore",
        summary="We chose PostgreSQL for the ledger service.",
        source_message_ids=["m1", "m2"],
        importance=0.8,
        created_at="t1",
    )
    base.update(over)
    return Episode(**base)


def _memory(**over) -> StructuredMemory:
    base = dict(
        id="mem_live",
        conversation_id="conv_live",
        type="decision",
        key="ledger datastore",
        value="PostgreSQL",
        source_message_ids=["m1"],
        scope_type="project",
        scope_id="proj_live",
        importance=0.7,
        updated_at="t1",
    )
    base.update(over)
    return StructuredMemory(**base)


def _names(client) -> set[str]:
    """Collection names, tolerant of old/new chroma ``list_collections``."""

    return {getattr(c, "name", c) for c in client.list_collections()}


class TestLiveRoundTrip:
    def test_episode_and_memory_survive_a_restart(self, live_root):
        vector.index_episode("u_live", "s_live", "proj_live", _episode())
        vector.index_memory(
            "u_live", "s_live", "proj_live", "conv_live", _memory()
        )

        # Drop every open handle, exactly like a Brain restart would.
        vector.reset()

        ep_hits = vector.query_episodes(
            "u_live", "proj_live", "which datastore for the ledger", k=3
        )
        assert "ep_live" in [hit[0] for hit in ep_hits]

        mem_hits = vector.query_memories(
            "u_live", "ledger datastore", k=3, project_id="proj_live"
        )
        assert "mem_live" in [hit[0] for hit in mem_hits]

    def test_provenance_metadata_persists_on_disk(self, live_root):
        vector.index_memory(
            "u_live", "s_live", "proj_live", "conv_live", _memory()
        )
        vector.reset()

        coll = vector._get_collection(vector._MEMORY_COLLECTION)
        assert coll is not None
        got = coll.get(ids=["mem_live"])
        meta = got["metadatas"][0]
        assert meta["memory_id"] == "mem_live"
        assert meta["scope_type"] == "project"
        assert meta["scope_id"] == "proj_live"
        assert meta["project"] == "proj_live"
        assert meta["conversation_id"] == "conv_live"
        assert meta["memory_type"] == "decision"
        assert meta["status"] == "active"

    def test_user_scoped_filters_hold_under_real_chroma(self, live_root):
        vector.index_memory(
            "u_live", "s_live", "proj_live", "conv_live", _memory()
        )
        vector.reset()

        # A different user must never see u_live's index (§16).
        assert vector.query_memories("u_other", "ledger", k=5) == []
        # scope_type filter is honoured by the real where-clause.
        assert vector.query_memories(
            "u_live", "ledger", k=5, project_id="proj_live", scope_type="project"
        )
        assert (
            vector.query_memories(
                "u_live",
                "ledger",
                k=5,
                project_id="proj_live",
                scope_type="conversation",
            )
            == []
        )


class TestLiveLegacyMigration:
    def test_eigent_episodes_is_copied_then_dropped(self, live_root):
        import chromadb

        client = chromadb.PersistentClient(path=str(live_root))
        legacy = client.get_or_create_collection("eigent_episodes")
        legacy.upsert(
            ids=["legacy_ep"],
            documents=["Decided to use SQLite for the prototype."],
            metadatas=[
                {
                    "user": "u_live",
                    "space": "s_live",
                    "project": "proj_live",
                    "conversation_id": "conv_live",
                    "episode_id": "legacy_ep",
                    "source_message_ids": "[]",
                    "source_message_count": 0,
                    "start_turn": 0,
                    "end_turn": 1,
                    "importance": 0.5,
                    "created_at": "t0",
                    "status": "active",
                }
            ],
        )

        vector.reset()  # next open must run the rename migration
        coll = vector._get_collection(vector._EPISODE_COLLECTION)
        assert coll is not None
        assert coll.get(ids=["legacy_ep"])["ids"] == ["legacy_ep"]

        names = _names(client)
        assert "undisclosed_episodes" in names
        assert "eigent_episodes" not in names

    def test_migration_is_a_noop_without_a_legacy_collection(self, live_root):
        coll = vector._get_collection(vector._EPISODE_COLLECTION)
        assert coll is not None
        assert coll.count() == 0
