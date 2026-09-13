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

"""MemoryToolkit.recall_conversation / recall_turns tests.

The key behaviour: a BROAD query ("the plan", "what we decided") is answered by
the cumulative summary, not a raw keyword scan that returns fragments.
"""

from __future__ import annotations

from app.agent.toolkit.memory_toolkit import MemoryToolkit
from app.memory import LocalMemoryStore, RollingSummary, build_turn_digest
from app.memory.rolling_summary import append_turn


def _seed(store: LocalMemoryStore, ids: dict[str, str]) -> None:
    store.write_project_summary(
        ids["user_key"],
        ids["space_id"],
        ids["project_id"],
        "Conversation so far (cumulative):\n"
        "- Turn 1 [done] user: diagnose\n  did: found pricing change",
    )

    def _mutate(payload):
        current = RollingSummary.from_dict(payload) or RollingSummary(
            project_id=ids["project_id"]
        )
        current = append_turn(
            current,
            build_turn_digest(
                query_id="run_1",
                status="done",
                user_prompt="diagnose the drop",
                final_result="Found the pricing change. Fix planned.",
            ),
        )
        return current.to_dict()

    store.update_project_summary_json(
        ids["user_key"], ids["space_id"], ids["project_id"], _mutate
    )


def _toolkit(store: LocalMemoryStore, ids: dict[str, str]) -> MemoryToolkit:
    return MemoryToolkit(
        api_task_id=ids["project_id"],
        user_key=ids["user_key"],
        space_id=ids["space_id"],
        store=store,
    )


def _ids() -> dict[str, str]:
    return {
        "user_key": "user_42",
        "space_id": "space_x",
        "project_id": "project_x",
    }


def test_broad_query_returns_cumulative_summary(tmp_path):
    store = LocalMemoryStore(root=tmp_path)
    ids = _ids()
    _seed(store, ids)
    toolkit = _toolkit(store, ids)

    result = toolkit.recall_conversation("what was the plan again?")
    assert "Conversation so far (cumulative):" in result
    assert "diagnose" in result


def test_narrow_query_falls_back_to_summary_when_no_turn_match(tmp_path):
    store = LocalMemoryStore(root=tmp_path)
    ids = _ids()
    _seed(store, ids)
    toolkit = _toolkit(store, ids)

    # No raw turn files exist for this project id, so the raw scan finds
    # nothing; the cumulative summary is the continuity fallback.
    result = toolkit.recall_conversation("zzz-unmatched-token")
    assert "cumulative" in result.lower()


def test_recall_turns_returns_structured_digests(tmp_path):
    store = LocalMemoryStore(root=tmp_path)
    ids = _ids()
    _seed(store, ids)
    toolkit = _toolkit(store, ids)

    result = toolkit.recall_turns(5)
    assert "Turn 1" in result
    assert "diagnose the drop" in result
    assert "pricing change" in result


def test_no_user_key_is_safe(tmp_path):
    store = LocalMemoryStore(root=tmp_path)
    toolkit = MemoryToolkit(
        api_task_id="project_x", user_key=None, space_id=None, store=store
    )
    assert "cumulative" not in toolkit.recall_turns(3).lower()
