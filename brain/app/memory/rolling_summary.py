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

"""Rolling conversation summary (cumulative, per Project).

The agent loses working context between turns: `run_turn` resets the reused
model's message history every turn (see `single_agent_service.run_turn`), and
the only durable context fed back is a thin tail that gists every assistant turn
to its first sentence. A plan or diagnosis lives in the assistant body, so it is
dropped, and the next turn re-derives it (or calls `recall_conversation`, which
returns fragments).

This module maintains ONE cumulative summary document per conversation
(`project_id`) and merges each turn into it:

    new_summary = merge(previous_cumulative_summary, this_turn_digest)

Turn N's stored summary is therefore always a summary of turns 1..N together,
never a bag of independent per-turn summaries. That is what stops detail from
decaying.

Two files per Project (both under the existing LocalMemoryStore tree):

    <project>/summary.json   source of truth: structured turn digests + rolling
    <project>/summary.md     rendered, budgeted view injected into the prompt

The `.md` is the small, cache-friendly text; the `.json` lets us compact,
re-render, and backfill without a model call. Everything here is fully
deterministic and makes ZERO model calls, so an ordinary turn costs nothing
extra. Overflow compaction folds the oldest turns into the `rolling` narrative
instead of calling a model; a model-backed merge remains a documented follow-up
because `on_run_end` is synchronous (no event loop to await an LLM on).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger("memory.rolling_summary")

SCHEMA_VERSION: int = 1

# Per-field hard caps so one pathological turn (an HTML report dumped as the
# answer) can't dominate the rendered document.
_USER_MAX_CHARS = 300
_DID_MAX_CHARS = 500
_ROLLING_MAX_CHARS = 2000
_MAX_FILES = 20
_FILE_MAX_CHARS = 200

# Tools whose arguments name a file/path the turn touched. Matched as
# substrings so `write_file`, `edit_file`, `apply_patch`, `str_replace_editor`,
# etc. all count without a brittle exact-name table.
_FILE_TOOL_HINTS = (
    "write_file",
    "edit_file",
    "create_file",
    "apply_patch",
    "str_replace",
    "notebook_edit",
)
_FILE_ARG_KEYS = (
    "file_path",
    "filename",
    "path",
    "file",
    "notebook_path",
)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %d", name, raw, default)
        return default


def enabled() -> bool:
    """Master switch. Default on (Phase 1 is deterministic + free)."""
    return _env_flag("UNDISCLOSED_ROLLING_SUMMARY", True)


def char_budget() -> int:
    """Rendered `.md` size above which compaction folds older turns."""
    return _env_int("UNDISCLOSED_ROLLING_SUMMARY_CHAR_BUDGET", 6000)


def keep_turns() -> int:
    """Recent turns kept at full digest detail; older ones fold into rolling."""
    return max(1, _env_int("UNDISCLOSED_ROLLING_SUMMARY_KEEP_TURNS", 8))


def backfill_enabled() -> bool:
    """Lazily build an initial summary for Projects that predate this feature."""
    return _env_flag("UNDISCLOSED_ROLLING_SUMMARY_BACKFILL", True)


# ----- Text helpers -----


def _collapse(text: str) -> str:
    return " ".join((text or "").split())


def _truncate(text: str, max_chars: int, ellipsis: str = "...") -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - len(ellipsis))] + ellipsis


def _did_line(text: str, max_chars: int) -> str:
    """The "what the assistant did" line: collapsed prose, hard-capped.

    Deliberately NOT just the first sentence -- a diagnosis or multi-step plan
    often spans the opening sentences, and dropping everything after the first
    period is exactly the decay this feature exists to fix. The cap keeps one
    oversized answer (an HTML report) from dominating the document.
    """

    return _truncate(_collapse(text), max_chars)


# ----- Schema -----


@dataclass
class TurnDigest:
    """What one user turn did, in a form the next turn can act on."""

    n: int
    query_id: str
    ts: str
    status: str  # "done" | "failed" | "cancelled"
    user: str  # the user's message, verbatim (bounded)
    did: str  # 1-3 line gist of what the assistant did
    files: list[str] = field(default_factory=list)
    next: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Any) -> TurnDigest | None:
        if not isinstance(payload, dict):
            return None
        try:
            n = int(payload.get("n") or 0)
        except (TypeError, ValueError):
            n = 0
        files = payload.get("files")
        return cls(
            n=n,
            query_id=str(payload.get("query_id") or ""),
            ts=str(payload.get("ts") or ""),
            status=str(payload.get("status") or "done"),
            user=str(payload.get("user") or ""),
            did=str(payload.get("did") or ""),
            files=[str(f) for f in files] if isinstance(files, list) else [],
            next=str(payload.get("next") or ""),
        )


@dataclass
class RollingSummary:
    """The cumulative summary document for one Project/conversation."""

    project_id: str
    turn_count: int = 0
    updated_at: str = ""
    rolling: str = ""
    turns: list[TurnDigest] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "turn_count": self.turn_count,
            "updated_at": self.updated_at,
            "rolling": self.rolling,
            "turns": [t.to_dict() for t in self.turns],
        }

    @classmethod
    def from_dict(cls, payload: Any) -> RollingSummary | None:
        if not isinstance(payload, dict):
            return None
        raw_turns = payload.get("turns")
        turns: list[TurnDigest] = []
        if isinstance(raw_turns, list):
            for row in raw_turns:
                digest = TurnDigest.from_dict(row)
                if digest is not None:
                    turns.append(digest)
        try:
            turn_count = int(payload.get("turn_count") or len(turns))
        except (TypeError, ValueError):
            turn_count = len(turns)
        try:
            schema_version = int(
                payload.get("schema_version") or SCHEMA_VERSION
            )
        except (TypeError, ValueError):
            schema_version = SCHEMA_VERSION
        return cls(
            project_id=str(payload.get("project_id") or ""),
            turn_count=turn_count,
            updated_at=str(payload.get("updated_at") or ""),
            rolling=str(payload.get("rolling") or ""),
            turns=turns,
            schema_version=schema_version,
        )


# ----- Digest construction -----


def build_turn_digest(
    *,
    query_id: str,
    status: str,
    user_prompt: str | None,
    final_result: str | None = None,
    summary: str | None = None,
    error: str | None = None,
    ts: str = "",
    files: list[str] | None = None,
    n: int = 0,
) -> TurnDigest:
    """Deterministically build one turn's digest (no model call)."""

    user = _truncate(_collapse(user_prompt or ""), _USER_MAX_CHARS)
    did_source = (summary or "").strip() or (final_result or "").strip()
    did = _did_line(did_source, _DID_MAX_CHARS)
    if not did and error:
        did = _truncate(f"failed: {_collapse(error)}", _DID_MAX_CHARS)
    if not did:
        did = "(no result recorded)"
    clean_files = _dedupe_files(files or [])
    return TurnDigest(
        n=n,
        query_id=query_id,
        ts=ts,
        status=status or "done",
        user=user,
        did=did,
        files=clean_files,
        next="",
    )


def _dedupe_files(files: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for raw in files:
        path = _truncate(_collapse(str(raw)), _FILE_MAX_CHARS)
        if not path:
            continue
        seen.setdefault(path, None)
        if len(seen) >= _MAX_FILES:
            break
    return list(seen.keys())


def extract_touched_files(tool_events: list[dict[str, Any]]) -> list[str]:
    """Best-effort list of file paths a run's tool events touched.

    Pure, tolerant of schema drift: unknown/malformed rows are skipped. Used to
    enrich the digest; a miss only means the summary is slightly less specific,
    never a failure.
    """

    paths: list[str] = []
    for row in tool_events or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("tool_name") or "").lower()
        if not any(hint in name for hint in _FILE_TOOL_HINTS):
            continue
        args = row.get("arguments")
        if not isinstance(args, dict):
            continue
        for key in _FILE_ARG_KEYS:
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                paths.append(value)
    return _dedupe_files(paths)


# ----- Merge / render / compact -----


def _rolling_append(rolling: str, digest: TurnDigest) -> str:
    """Fold a turn into the cumulative rolling narrative (deterministic)."""

    piece = f"Turn {digest.n}: {digest.user} -> {digest.did}".strip()
    merged = f"{rolling} {piece}".strip() if rolling else piece
    if len(merged) > _ROLLING_MAX_CHARS:
        # Keep the newest tail: recent context matters most.
        merged = "..." + merged[-_ROLLING_MAX_CHARS:]
    return merged


def merge(summary: RollingSummary, digest: TurnDigest) -> RollingSummary:
    """Append a turn to the cumulative summary (idempotent per query_id).

    This is the core invariant: the input is the PREVIOUS cumulative state, so
    the result summarizes every turn seen so far, not just the newest one.
    """

    turns = list(summary.turns)
    existing_idx = next(
        (i for i, t in enumerate(turns) if t.query_id == digest.query_id),
        None,
    )
    if existing_idx is not None:
        # Same run finalized twice; update in place, keep its position.
        merged_digest = TurnDigest(
            n=turns[existing_idx].n or digest.n,
            query_id=digest.query_id,
            ts=digest.ts or turns[existing_idx].ts,
            status=digest.status,
            user=digest.user or turns[existing_idx].user,
            did=digest.did or turns[existing_idx].did,
            files=digest.files or turns[existing_idx].files,
            next=digest.next or turns[existing_idx].next,
        )
        turns[existing_idx] = merged_digest
    else:
        next_n = max((t.n for t in turns), default=0) + 1
        turns.append(
            TurnDigest(
                n=next_n,
                query_id=digest.query_id,
                ts=digest.ts,
                status=digest.status,
                user=digest.user,
                did=digest.did,
                files=digest.files,
                next=digest.next,
            )
        )
    turns.sort(key=lambda t: t.n)
    return RollingSummary(
        project_id=summary.project_id,
        turn_count=len(turns),
        updated_at=summary.updated_at,
        rolling=summary.rolling,
        turns=turns,
        schema_version=summary.schema_version,
    )


def append_turn(summary: RollingSummary, digest: TurnDigest) -> RollingSummary:
    """Alias for `merge` — reads better at the call site."""
    return merge(summary, digest)


def compact_if_over_budget(
    summary: RollingSummary,
    budget: int | None = None,
    keep: int | None = None,
) -> RollingSummary:
    """Fold the oldest turns into `rolling` while the render exceeds budget.

    Compaction never drops information: folded turns survive inside `rolling`
    (bounded). Recent `keep` turns stay at full digest detail.
    """

    budget = char_budget() if budget is None else budget
    keep = keep_turns() if keep is None else keep
    out = RollingSummary(
        project_id=summary.project_id,
        turn_count=summary.turn_count,
        updated_at=summary.updated_at,
        rolling=summary.rolling,
        turns=list(summary.turns),
        schema_version=summary.schema_version,
    )
    while len(out.turns) > keep and len(render_md(out)) > budget:
        oldest = out.turns.pop(0)
        out.rolling = _rolling_append(out.rolling, oldest)
    return out


def render_md(summary: RollingSummary) -> str:
    """Render the cumulative summary as bounded markdown for prompt injection."""

    lines: list[str] = ["Conversation so far (cumulative):"]
    header = f"turns 1..{summary.turn_count}"
    if summary.updated_at:
        header += f" · updated {summary.updated_at}"
    lines.append(f"_{header}_")
    if summary.rolling:
        lines.append("")
        lines.append(_truncate(_collapse(summary.rolling), _ROLLING_MAX_CHARS))
    if summary.turns:
        lines.append("")
        lines.append("Turn history (oldest to newest):")
        for turn in summary.turns:
            lines.append(f"- Turn {turn.n} [{turn.status}] user: {turn.user}")
            if turn.did:
                lines.append(f"  did: {turn.did}")
            if turn.files:
                lines.append(f"  files: {', '.join(turn.files)}")
            if turn.next:
                lines.append(f"  next: {turn.next}")
    return "\n".join(lines).strip() + "\n"


def backfill_from_conversation(
    events: list[Any],
    *,
    project_id: str,
    updated_at: str = "",
    max_turns: int | None = None,
) -> RollingSummary:
    """Build an initial cumulative summary from a Project's conversation log.

    Lets already-broken conversations recover instead of only new ones. Pairs
    user/assistant events by `run_id`; assistant text is gisted (same rule the
    live path uses). Deterministic, no model call.
    """

    max_turns = max_turns or max(20, keep_turns() * 4)
    by_run: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for event in events or []:
        run_id = str(getattr(event, "run_id", "") or "")
        role = str(getattr(event, "role", "") or "")
        content = getattr(event, "content", "") or ""
        if not run_id or role not in ("user", "assistant"):
            continue
        if run_id not in by_run:
            by_run[run_id] = {}
            order.append(run_id)
        # Keep the first user message and the last assistant message per run.
        if role == "user" and content and not by_run[run_id].get("user"):
            by_run[run_id]["user"] = content
        elif role == "assistant" and content:
            by_run[run_id]["assistant"] = content

    summary = RollingSummary(project_id=project_id, updated_at=updated_at)
    for run_id in order[-max_turns:]:
        row = by_run[run_id]
        if not row.get("user") and not row.get("assistant"):
            continue
        digest = build_turn_digest(
            query_id=run_id,
            status="done",
            user_prompt=row.get("user", ""),
            final_result=row.get("assistant", ""),
            ts="",
        )
        summary = merge(summary, digest)
    summary.updated_at = updated_at
    return summary


def load(store: Any, user_key: str, space_id: str, project_id: str) -> RollingSummary | None:
    """Read the structured summary for a Project (None when absent/corrupt)."""

    try:
        payload = store.read_project_summary_json(user_key, space_id, project_id)
    except Exception:  # noqa: BLE001 — best-effort read
        logger.debug("rolling_summary.load failed", exc_info=True)
        return None
    return RollingSummary.from_dict(payload)


def render_for_prompt(store: Any, user_key: str, space_id: str, project_id: str) -> str:
    """Convenience: load + render, returning "" on any failure."""

    summary = load(store, user_key, space_id, project_id)
    if summary is None or not summary.turns:
        return ""
    try:
        return render_md(summary)
    except Exception:  # noqa: BLE001
        logger.debug("rolling_summary.render failed", exc_info=True)
        return ""


def to_json(summary: RollingSummary) -> str:
    """Serialize for logging/debug (not used on the hot path)."""
    return json.dumps(summary.to_dict(), ensure_ascii=False)
