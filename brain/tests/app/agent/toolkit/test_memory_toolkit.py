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


def test_rule_is_saved_when_the_request_omits_space_id(tmp_path, monkeypatch):
    """A chat may send no space_id; a rule must still reach the always-on store.

    RunContext resolves the space as ``space_id or project_id``, so the toolkit
    has to do the same or the structured write fails while the index succeeds.
    """
    from app.agent.toolkit import memory_toolkit as mt_mod
    from app.memory.hybrid.rules import read_active_rules

    monkeypatch.setattr(mt_mod.semantic_store, "remember", lambda *a, **k: None)
    store = LocalMemoryStore(root=tmp_path)
    toolkit = MemoryToolkit(
        api_task_id="project_x", user_key="user_42", space_id=None, store=store
    )

    result = toolkit.remember_fact(
        fact="Always run the license header check before committing",
        kind="rule",
        scope="global",
        key="",
        category="licensing",
    )

    assert result == "Saved to memory."
    rules = read_active_rules(
        store,
        user_key="user_42",
        space_id="project_x",
        project_id="project_x",
        conversation_id="project_x",
    )
    assert [r.value for r in rules] == [
        "Always run the license header check before committing"
    ]
    assert rules[0].severity == "hard"
    assert rules[0].scope_type == "global"


def test_rule_write_failure_names_the_reason(tmp_path, monkeypatch):
    from app.agent.toolkit import memory_toolkit as mt_mod

    monkeypatch.setattr(mt_mod.semantic_store, "remember", lambda *a, **k: None)
    store = LocalMemoryStore(root=tmp_path)
    toolkit = MemoryToolkit(
        api_task_id="project_x", user_key=None, space_id="space_x", store=store
    )

    result = toolkit.remember_fact(
        fact="Always run the license header check before committing",
        kind="rule",
        scope="global",
        key="",
        category="licensing",
    )

    #not the old blanket "store was unavailable": the reason is the user key.
    assert "no user key" in result


def test_rule_write_exception_is_reported_not_raised(tmp_path, monkeypatch):
    from app.agent.toolkit import memory_toolkit as mt_mod

    monkeypatch.setattr(mt_mod.semantic_store, "remember", lambda *a, **k: None)

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(mt_mod.GlobalMemoryStore, "apply_ops", _boom)
    store = LocalMemoryStore(root=tmp_path)
    toolkit = MemoryToolkit(
        api_task_id="project_x", user_key="user_42", space_id="space_x", store=store
    )

    result = toolkit.remember_fact(
        fact="Always run the license header check before committing",
        kind="rule",
        scope="global",
        key="",
        category="licensing",
    )

    assert "store write raised OSError" in result


def test_restated_legacy_rule_reports_saved_and_is_not_duplicated(
    tmp_path, monkeypatch
):
    from app.agent.toolkit import memory_toolkit as mt_mod
    from app.memory.hybrid.schema import MemoryOp
    from app.memory.hybrid.scope import GlobalMemoryStore

    monkeypatch.setattr(mt_mod.semantic_store, "remember", lambda *a, **k: None)
    store = LocalMemoryStore(root=tmp_path)
    GlobalMemoryStore(store).apply_ops(
        "user_42",
        "space_x",
        "project_x",
        [
            MemoryOp(
                op="UPSERT",
                type="constraint",
                key="license_rule_reminder",
                value="always remember the previously given license rule",
            )
        ],
        conversation_id="project_x",
        now="2026-01-01T00:00:00+00:00",
        scope_type="global",
        scope_id="user_42",
        user_id="user_42",
    )
    toolkit = MemoryToolkit(
        api_task_id="project_x", user_key="user_42", space_id="space_x", store=store
    )

    result = toolkit.remember_fact(
        fact="always remember the previously given license rule",
        kind="rule",
        scope="global",
        key="",
        category="licensing",
    )

    assert result == "Saved to memory."
    active = [
        m
        for m in GlobalMemoryStore(store).read_active_memories(
            "user_42", "space_x", "project_x"
        )
        if m.type == "constraint"
    ]
    assert len(active) == 1
    assert active[0].key == "license_rule_reminder"
    assert active[0].severity == "hard"
