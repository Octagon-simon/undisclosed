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

"""Optional LLM extraction pass: gating, parsing/validation, shadow + write.

No test here calls a real model: every extraction is driven by an injected
``completer`` (or a monkeypatched ``llm_extract.extract``), so the suite stays
deterministic and offline.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from app.memory.events import ConversationEvent
from app.memory.hybrid import config, engine, llm_extract
from app.memory.hybrid.schema import (
    EpisodeDraft,
    ExtractionResult,
    MemoryOp,
)
from app.memory.local_store import read_jsonl_file

IDS = {
    "user_key": "user_42",
    "space_id": "space_test",
    "project_id": "project_test",
    "conversation_id": "project_test",
}


def _event(idx: int, role: str, content: str, run_id: str | None = None):
    return ConversationEvent(
        event_id=f"evt_{idx}_{role}",
        run_id=run_id or f"run{idx}",
        timestamp="t",
        role=role,  # type: ignore[arg-type]
        content=content,
        source="chat",
        visibility="context",
        hash="sha256:x",
    )


def _append_run(store, run_idx: int, user: str, assistant: str) -> None:
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


def _completer(raw: str) -> Callable[[str, str], str]:
    def _complete(_system: str, _user: str) -> str:
        return raw

    return _complete


_VALID = json.dumps(
    {
        "episode": {
            "title": "DB migration",
            "summary": "Chose PostgreSQL for the database.",
            "objective": "Pick the database",
            "topic": "database, postgres",
            "importance": 0.8,
            "decisions": ["use PostgreSQL"],
        },
        "memoryOps": [
            {
                "op": "UPSERT",
                "type": "decision",
                "key": "database",
                "value": "PostgreSQL",
                "sourceMessageIds": ["evt_1_user"],
            }
        ],
    }
)


class TestModeConfig:
    def test_default_is_off(self, monkeypatch):
        monkeypatch.delenv("UNDISCLOSED_HYBRID_LLM_EXTRACTION", raising=False)
        assert config.llm_extraction_mode() == config.LLM_EXTRACTION_OFF

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on", "shadow"])
    def test_truthy_values_shadow(self, monkeypatch, value):
        monkeypatch.setenv("UNDISCLOSED_HYBRID_LLM_EXTRACTION", value)
        assert config.llm_extraction_mode() == config.LLM_EXTRACTION_SHADOW

    @pytest.mark.parametrize("value", ["write", "authoritative", "live"])
    def test_write_values_are_authoritative(self, monkeypatch, value):
        monkeypatch.setenv("UNDISCLOSED_HYBRID_LLM_EXTRACTION", value)
        assert config.llm_extraction_mode() == config.LLM_EXTRACTION_WRITE

    @pytest.mark.parametrize("value", ["off", "false", "0"])
    def test_off_values(self, monkeypatch, value):
        monkeypatch.setenv("UNDISCLOSED_HYBRID_LLM_EXTRACTION", value)
        assert config.llm_extraction_mode() == config.LLM_EXTRACTION_OFF

    def test_unknown_value_falls_back_to_off(self, monkeypatch):
        monkeypatch.setenv("UNDISCLOSED_HYBRID_LLM_EXTRACTION", "banana")
        assert config.llm_extraction_mode() == config.LLM_EXTRACTION_OFF


class TestGate:
    def test_short_slice_is_skipped(self):
        events = [_event(1, "user", "we'll use PostgreSQL for the database")]
        assert llm_extract.worth_extracting(events, min_events=4) is False

    def test_chatter_only_is_skipped(self):
        events = [
            _event(i, "user" if i % 2 else "assistant", "ok") for i in range(1, 7)
        ]
        assert llm_extract.worth_extracting(events, min_events=4) is False

    def test_substantive_slice_passes(self):
        events = [
            _event(1, "user", "we'll use PostgreSQL for the database"),
            _event(2, "assistant", "Understood, wiring it up."),
            _event(3, "user", "and add a connection pool"),
            _event(4, "assistant", "Done."),
        ]
        assert llm_extract.worth_extracting(events, min_events=4) is True


class TestExtract:
    def _events(self) -> list[ConversationEvent]:
        return [
            _event(1, "user", "we'll use PostgreSQL for the database"),
            _event(2, "assistant", "Noted."),
            _event(3, "user", "and add a connection pool"),
            _event(4, "assistant", "Done."),
        ]

    def test_parses_valid_payload(self):
        result = llm_extract.extract(
            self._events(), turns=[1, 2, 3, 4], completer=_completer(_VALID)
        )
        assert result is not None
        assert result.episode.title == "DB migration"
        assert result.episode.importance == 0.8
        assert [(op.type, op.value) for op in result.memory_ops] == [
            ("decision", "PostgreSQL")
        ]

    def test_fenced_json_is_parsed(self):
        raw = f"```json\n{_VALID}\n```"
        assert llm_extract.extract(
            self._events(), completer=_completer(raw)
        ) is not None

    def test_garbage_returns_none(self):
        assert (
            llm_extract.extract(
                self._events(), completer=_completer("not json at all")
            )
            is None
        )

    def test_model_error_returns_none(self):
        def _boom(_system: str, _user: str) -> str:
            raise RuntimeError("timeout")

        assert llm_extract.extract(self._events(), completer=_boom) is None

    def test_unavailable_model_returns_none(self, monkeypatch):
        monkeypatch.delenv("UNDISCLOSED_HYBRID_LLM_EXTRACTION", raising=False)
        # No completer injected and the pass is off -> no call is attempted.
        assert llm_extract.extract(self._events()) is None

    def _payload(self, ops: list[dict]) -> str:
        return json.dumps({"episode": {"summary": "something"}, "memoryOps": ops})

    def test_op_with_unknown_source_is_dropped(self):
        raw = self._payload(
            [
                {
                    "op": "UPSERT",
                    "type": "decision",
                    "key": "database",
                    "value": "MySQL",
                    "sourceMessageIds": ["evt_999_user"],
                }
            ]
        )
        result = llm_extract.extract(self._events(), completer=_completer(raw))
        assert result is not None and result.memory_ops == []

    def test_op_without_source_is_dropped(self):
        raw = self._payload(
            [
                {
                    "op": "UPSERT",
                    "type": "decision",
                    "key": "database",
                    "value": "MySQL",
                }
            ]
        )
        result = llm_extract.extract(self._events(), completer=_completer(raw))
        assert result is not None and result.memory_ops == []

    def test_unknown_type_is_dropped(self):
        raw = self._payload(
            [
                {
                    "op": "UPSERT",
                    "type": "vibe",
                    "key": "database",
                    "value": "MySQL",
                    "sourceMessageIds": ["evt_1_user"],
                }
            ]
        )
        result = llm_extract.extract(self._events(), completer=_completer(raw))
        assert result is not None and result.memory_ops == []

    def test_unknown_verb_is_dropped(self):
        raw = self._payload(
            [
                {
                    "op": "NUKE",
                    "type": "decision",
                    "key": "database",
                    "value": "MySQL",
                    "sourceMessageIds": ["evt_1_user"],
                }
            ]
        )
        result = llm_extract.extract(self._events(), completer=_completer(raw))
        assert result is not None and result.memory_ops == []

    def test_empty_value_is_dropped(self):
        raw = self._payload(
            [
                {
                    "op": "UPSERT",
                    "type": "decision",
                    "key": "database",
                    "value": "   ",
                    "sourceMessageIds": ["evt_1_user"],
                }
            ]
        )
        result = llm_extract.extract(self._events(), completer=_completer(raw))
        assert result is not None and result.memory_ops == []

    def test_targeted_op_with_known_source_is_kept(self):
        raw = self._payload(
            [
                {
                    "op": "SUPERSEDE",
                    "memoryId": "mem_1",
                    "sourceMessageIds": ["evt_3_user"],
                }
            ]
        )
        result = llm_extract.extract(self._events(), completer=_completer(raw))
        assert result is not None
        assert [op.memory_id for op in result.memory_ops] == ["mem_1"]

    def test_empty_episode_and_no_ops_returns_none(self):
        raw = json.dumps({"episode": {"title": "x"}, "memoryOps": []})
        assert (
            llm_extract.extract(self._events(), completer=_completer(raw)) is None
        )


class TestApplyOpsProvenance:
    def _op(self, source_ids: list[str]) -> MemoryOp:
        return MemoryOp(
            op="UPSERT",
            type="decision",
            key="database",
            value="MongoDB",
            source_message_ids=source_ids,
        )

    def test_unknown_source_is_dropped_when_ids_supplied(self, hybrid, ids):
        u = ids["user_key"], ids["space_id"], ids["project_id"]
        hybrid.apply_ops(
            *u,
            [self._op(["ghost_msg"])],
            conversation_id="c",
            now="t1",
            valid_source_ids={"real_msg"},
        )
        assert hybrid.read_memories(*u) == []

    def test_known_source_is_kept(self, hybrid, ids):
        u = ids["user_key"], ids["space_id"], ids["project_id"]
        hybrid.apply_ops(
            *u,
            [self._op(["real_msg"])],
            conversation_id="c",
            now="t1",
            valid_source_ids={"real_msg"},
        )
        assert [m.value for m in hybrid.read_active_memories(*u)] == ["MongoDB"]

    def test_no_check_when_ids_omitted(self, hybrid, ids):
        u = ids["user_key"], ids["space_id"], ids["project_id"]
        hybrid.apply_ops(
            *u, [self._op(["anything"])], conversation_id="c", now="t1"
        )
        assert [m.value for m in hybrid.read_active_memories(*u)] == ["MongoDB"]


class TestEngineIntegration:
    def _seed(self, store) -> None:
        _append_run(store, 1, "we'll use MongoDB for the database", "Noted.")
        _append_run(store, 2, "add an index on the users table", "Done.")
        _append_run(store, 3, "we'll use PostgreSQL for the database", "Noted.")

    def _run(self, hybrid) -> dict:
        return engine.process_run_end(
            hybrid,
            user_key=IDS["user_key"],
            space_id=IDS["space_id"],
            project_id=IDS["project_id"],
            conversation_id=IDS["conversation_id"],
            budget_tokens=5,
        )

    def _log_path(self, hybrid):
        return (
            hybrid.base.project_path(
                IDS["user_key"], IDS["space_id"], IDS["project_id"]
            )
            / "extraction_log.jsonl"
        )

    def test_off_mode_never_calls_the_model(self, hybrid, monkeypatch):
        monkeypatch.delenv("UNDISCLOSED_HYBRID_LLM_EXTRACTION", raising=False)
        calls = {"n": 0}

        def _fake(*_a, **_k):
            calls["n"] += 1
            return None

        monkeypatch.setattr(llm_extract, "extract", _fake)
        self._seed(hybrid.base)
        summary = self._run(hybrid)
        assert summary["llm_extraction"] == "off"
        assert calls["n"] == 0
        assert not self._log_path(hybrid).exists()

    def test_shadow_logs_comparison_but_writes_nothing(self, hybrid, monkeypatch):
        monkeypatch.setenv("UNDISCLOSED_HYBRID_LLM_EXTRACTION", "shadow")
        llm_result = ExtractionResult(
            episode=EpisodeDraft(
                title="LLM title", summary="LLM summary", importance=0.95
            ),
            memory_ops=[
                MemoryOp(
                    op="UPSERT",
                    type="fact",
                    key="llm_only_key",
                    value="llm only value",
                    source_message_ids=["evt_1_user"],
                )
            ],
        )
        monkeypatch.setattr(llm_extract, "extract", lambda *_a, **_k: llm_result)
        self._seed(hybrid.base)
        self._run(hybrid)

        rows = read_jsonl_file(self._log_path(hybrid))
        assert rows and any(row.get("llm") for row in rows)
        assert {row["phase"] for row in rows} <= {"episode", "turn"}
        assert all(row["mode"] == "shadow" for row in rows)

        # The model's op never lands, and the episode prose is untouched.
        active = hybrid.read_active_memories(
            IDS["user_key"], IDS["space_id"], IDS["project_id"]
        )
        assert not any(m.key == "llm_only_key" for m in active)
        episodes = hybrid.read_episodes(
            IDS["user_key"], IDS["space_id"], IDS["project_id"]
        )
        assert all(e.title != "LLM title" for e in episodes)
        # The deterministic planner still wrote its own decision.
        assert any(
            m.key == "database" and m.value == "PostgreSQL for the database"
            for m in active
        )

    def test_write_mode_applies_llm_episode_and_ops(self, hybrid, monkeypatch):
        monkeypatch.setenv("UNDISCLOSED_HYBRID_LLM_EXTRACTION", "write")
        llm_result = ExtractionResult(
            episode=EpisodeDraft(
                title="LLM title", summary="LLM summary", importance=0.95
            ),
            memory_ops=[
                MemoryOp(
                    op="UPSERT",
                    type="fact",
                    key="llm_only_key",
                    value="llm only value",
                    source_message_ids=["evt_1_user"],
                )
            ],
        )
        monkeypatch.setattr(llm_extract, "extract", lambda *_a, **_k: llm_result)
        self._seed(hybrid.base)
        self._run(hybrid)

        episodes = hybrid.read_episodes(
            IDS["user_key"], IDS["space_id"], IDS["project_id"]
        )
        assert any(e.title == "LLM title" for e in episodes)
        active = hybrid.read_active_memories(
            IDS["user_key"], IDS["space_id"], IDS["project_id"]
        )
        assert any(m.key == "llm_only_key" for m in active)

    def test_write_mode_falls_back_when_model_returns_nothing(
        self, hybrid, monkeypatch
    ):
        monkeypatch.setenv("UNDISCLOSED_HYBRID_LLM_EXTRACTION", "write")
        monkeypatch.setattr(llm_extract, "extract", lambda *_a, **_k: None)
        self._seed(hybrid.base)
        self._run(hybrid)

        active = hybrid.read_active_memories(
            IDS["user_key"], IDS["space_id"], IDS["project_id"]
        )
        # Deterministic extraction still produced the current decision.
        assert any(
            m.key == "database" and m.value == "PostgreSQL for the database"
            for m in active
        )

    def test_llm_op_with_invented_source_is_rejected_by_store(
        self, hybrid, monkeypatch
    ):
        monkeypatch.setenv("UNDISCLOSED_HYBRID_LLM_EXTRACTION", "write")
        llm_result = ExtractionResult(
            episode=EpisodeDraft(summary="LLM summary"),
            memory_ops=[
                MemoryOp(
                    op="UPSERT",
                    type="decision",
                    key="invented",
                    value="hallucinated",
                    source_message_ids=["evt_does_not_exist"],
                )
            ],
        )
        monkeypatch.setattr(llm_extract, "extract", lambda *_a, **_k: llm_result)
        self._seed(hybrid.base)
        self._run(hybrid)

        active = hybrid.read_active_memories(
            IDS["user_key"], IDS["space_id"], IDS["project_id"]
        )
        assert not any(m.key == "invented" for m in active)
