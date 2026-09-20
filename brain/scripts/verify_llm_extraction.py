"""End-to-end smoke check for the optional LLM extraction pass.

Drives the REAL engine pipeline (`engine.process_run_end`) with a stubbed model
completer, so it exercises gating -> prompt build -> parse/validate -> shadow
logging -> the store mutation gate. No API key and no running app required.

Run:  cd brain && .venv/bin/python scripts/verify_llm_extraction.py
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from app.memory import LocalMemoryStore
from app.memory.events import ConversationEvent
from app.memory.hybrid import config, engine, llm_extract, vector
from app.memory.hybrid.storage import HybridStore
from app.memory.local_store import read_jsonl_file

IDS = {
    "user_key": "smoke_user",
    "space_id": "smoke_space",
    "project_id": "smoke_project",
    "conversation_id": "smoke_project",
}

OK = "\033[32mPASS\033[0m"
BAD = "\033[31mFAIL\033[0m"
_failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"  [{OK if cond else BAD}] {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        _failures.append(label)


def _append_run(store, idx: int, user: str, assistant: str) -> None:
    for role, content in (("user", user), ("assistant", assistant)):
        store.append_conversation(
            IDS["user_key"],
            IDS["space_id"],
            IDS["project_id"],
            ConversationEvent(
                event_id=f"evt_{idx}_{role}",
                run_id=f"run{idx}",
                timestamp="t",
                role=role,  # type: ignore[arg-type]
                content=content,
                source="chat",
                visibility="context",
                hash="sha256:x",
            ),
        )


def _seed(store) -> None:
    # Enough turns that an evicted episode slice clears the model gate
    # (llm_extraction_min_events, default 4 non-empty messages).
    _append_run(store, 1, "we'll use MongoDB for the database", "Noted.")
    _append_run(store, 2, "add an index on the users table", "Done.")
    _append_run(store, 3, "we'll use PostgreSQL for the database", "Noted.")
    _append_run(store, 4, "add a redis cache in front of the API", "Done.")
    _append_run(store, 5, "set the connection pool size to 20", "Done.")
    _append_run(store, 6, "we'll use PostgreSQL for the database", "Noted.")


def _model_payload(*, cite: str, summary: str, title: str) -> str:
    return json.dumps(
        {
            "episode": {"title": title, "summary": summary, "importance": 0.9},
            "memoryOps": [
                {
                    "op": "UPSERT",
                    "type": "decision",
                    "key": "smoke_llm_key",
                    "value": "smoke_llm_value",
                    "sourceMessageIds": [cite],
                }
            ],
        }
    )


def _stub_completer(real_ids_from_prompt: bool):
    """A fake model. Optionally cites a genuine id the prompt actually showed."""

    def _complete(_system: str, user: str) -> str:
        cite = "evt_DOES_NOT_EXIST"
        if real_ids_from_prompt:
            found = re.search(r"id=(\S+?)\s*\|", user)
            if found:
                cite = found.group(1)
        return _model_payload(
            cite=cite, summary="LLM-authored summary", title="LLM-authored title"
        )

    return _complete


def _run(hybrid: HybridStore) -> dict:
    return engine.process_run_end(
        hybrid,
        user_key=IDS["user_key"],
        space_id=IDS["space_id"],
        project_id=IDS["project_id"],
        conversation_id=IDS["conversation_id"],
        budget_tokens=5,
    )


def _log_path(hybrid: HybridStore) -> Path:
    return (
        hybrid.base.project_path(
            IDS["user_key"], IDS["space_id"], IDS["project_id"]
        )
        / "extraction_log.jsonl"
    )


def _fresh(name: str) -> tuple[LocalMemoryStore, HybridStore]:
    root = Path(tempfile.mkdtemp(prefix=f"hybrid-smoke-{name}-"))
    store = LocalMemoryStore(root=root / "memory")
    return store, HybridStore(store)


def scenario_default_off() -> None:
    print("\n== 1. Default (unset) is OFF: no model call, no log ==")
    os.environ.pop("UNDISCLOSED_HYBRID_LLM_EXTRACTION", None)
    check("mode is 'off'", config.llm_extraction_mode() == config.LLM_EXTRACTION_OFF)
    _store, hybrid = _fresh("off")
    calls = {"n": 0}

    def _never(*_a, **_k):
        calls["n"] += 1
        return None

    original = llm_extract.extract
    llm_extract.extract = _never  # type: ignore[assignment]
    try:
        _seed(hybrid.base)
        summary = _run(hybrid)
    finally:
        llm_extract.extract = original  # type: ignore[assignment]
    check(
        "summary reports off",
        summary.get("llm_extraction") == "off",
        str(summary.get("llm_extraction")),
    )
    check("model never called", calls["n"] == 0, f"calls={calls['n']}")
    check("no extraction_log.jsonl written", not _log_path(hybrid).exists())


def scenario_shadow() -> None:
    print("\n== 2. shadow: model runs, comparison is logged, nothing is written ==")
    os.environ["UNDISCLOSED_HYBRID_LLM_EXTRACTION"] = "shadow"
    _store, hybrid = _fresh("shadow")
    original = llm_extract._default_completer
    llm_extract._default_completer = lambda: _stub_completer(True)  # type: ignore[assignment]
    try:
        _seed(hybrid.base)
        summary = _run(hybrid)
    finally:
        llm_extract._default_completer = original  # type: ignore[assignment]

    check("summary reports shadow", summary.get("llm_extraction") == "shadow")
    log = _log_path(hybrid)
    check("extraction_log.jsonl exists", log.exists())
    rows = read_jsonl_file(log) if log.exists() else []
    check("log has rows", bool(rows), f"rows={len(rows)}")
    check("every row is shadow", all(r.get("mode") == "shadow" for r in rows))
    check("rows carry a deterministic side", any(r.get("deterministic") for r in rows))
    check("rows carry an llm side", any(r.get("llm") for r in rows))
    phases = sorted({r.get("phase") for r in rows})
    check("phases are episode/turn", set(phases) <= {"episode", "turn"}, str(phases))

    active = hybrid.read_active_memories(
        IDS["user_key"], IDS["space_id"], IDS["project_id"]
    )
    episodes = hybrid.read_episodes(
        IDS["user_key"], IDS["space_id"], IDS["project_id"]
    )
    check("model op did NOT land", not any(m.key == "smoke_llm_key" for m in active))
    check(
        "model title did NOT land",
        all("LLM-authored" not in e.title for e in episodes),
    )
    check(
        "deterministic decision still landed",
        any(
            m.key == "database" and m.value == "PostgreSQL for the database"
            for m in active
        ),
        ", ".join(f"{m.key}={m.value}" for m in active),
    )

    first_llm = next((r["llm"] for r in rows if r.get("llm")), None)
    if first_llm:
        print("\n  --- sample shadow row (llm side) ---")
        print("  " + json.dumps(first_llm, indent=2).replace("\n", "\n  "))


def scenario_write_provenance() -> None:
    print("\n== 3. write: valid provenance lands; invented provenance is dropped ==")
    os.environ["UNDISCLOSED_HYBRID_LLM_EXTRACTION"] = "write"

    # 3a. invented source id -> must be rejected by the gate
    _store, hybrid = _fresh("write-bad")
    original = llm_extract._default_completer
    llm_extract._default_completer = lambda: _stub_completer(False)  # type: ignore[assignment]
    try:
        _seed(hybrid.base)
        _run(hybrid)
    finally:
        llm_extract._default_completer = original  # type: ignore[assignment]
    active = hybrid.read_active_memories(
        IDS["user_key"], IDS["space_id"], IDS["project_id"]
    )
    check(
        "invented-provenance op rejected",
        not any(m.key == "smoke_llm_key" for m in active),
        ", ".join(f"{m.key}={m.value}" for m in active),
    )

    # 3b. real source id -> must land
    _store2, hybrid2 = _fresh("write-good")
    llm_extract._default_completer = lambda: _stub_completer(True)  # type: ignore[assignment]
    try:
        _seed(hybrid2.base)
        _run(hybrid2)
    finally:
        llm_extract._default_completer = original  # type: ignore[assignment]
    active2 = hybrid2.read_active_memories(
        IDS["user_key"], IDS["space_id"], IDS["project_id"]
    )
    episodes2 = hybrid2.read_episodes(
        IDS["user_key"], IDS["space_id"], IDS["project_id"]
    )
    check(
        "valid-provenance op landed",
        any(m.key == "smoke_llm_key" and m.value == "smoke_llm_value" for m in active2),
        ", ".join(f"{m.key}={m.value}" for m in active2),
    )
    check(
        "every landed memory retains provenance",
        all(m.source_message_ids for m in active2),
    )
    check(
        "model episode prose landed in write mode",
        any("LLM-authored" in e.title for e in episodes2),
    )
    check(
        "planner kept episode boundaries",
        all(e.start_turn <= e.end_turn for e in episodes2),
    )


def main() -> int:
    vector.disable()  # keep the real ~/.undisclosed tree untouched
    # The deterministic planner cuts this short seed into ~2-message episodes,
    # which is below the default gate (UNDISCLOSED_HYBRID_LLM_MIN_EVENTS=4), so
    # the episode pass would be skipped. Lower it to 2 so the episode *draft*
    # path (merge + write) is actually exercised. This is a real config knob.
    os.environ["UNDISCLOSED_HYBRID_LLM_MIN_EVENTS"] = "2"
    print("Hybrid memory: LLM extraction end-to-end smoke check")
    scenario_default_off()
    scenario_shadow()
    scenario_write_provenance()
    print()
    if _failures:
        print(f"\033[31m{len(_failures)} FAILURE(S):\033[0m " + "; ".join(_failures))
        return 1
    print("\033[32mALL CHECKS PASSED\033[0m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
