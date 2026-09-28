# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
# Portions Copyright 2026 Simon Ugorji. All Rights Reserved.
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
import re
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger("memory.rolling_summary")

SCHEMA_VERSION: int = 2

# Per-field hard caps so one pathological turn (an HTML report dumped as the
# answer) can't dominate the rendered document.
_USER_MAX_CHARS = 300
_DID_MAX_CHARS = 500
_ROLLING_MAX_CHARS = 2000
_MAX_FILES = 20
_FILE_MAX_CHARS = 200
# Handoff-only fields (commands run, verification evidence). These feed the
# EXPORT document, not the lean prompt view, so they don't inflate the context
# injected on every turn.
_COMMAND_MAX_CHARS = 300
_MAX_COMMANDS = 12
_VERIFY_MAX_CHARS = 300
_MAX_VERIFIED = 12
_NEXT_MAX_CHARS = 300

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

# Tools that RUN a command. Matched as substrings so `shell_exec`,
# `terminal_toolkit__shell_exec`, `run_command`, `execute`, `bash`, etc. all
# count without a brittle exact-name table.
_CMD_TOOL_HINTS = (
    "shell",
    "terminal",
    "exec",
    "bash",
    "command",
)
_CMD_ARG_KEYS = (
    "command",
    "cmd",
    "script",
    "code",
    "input",
)

# Commands that are acceptance/verification evidence rather than setup. Used to
# split "commands run" into "verified" vs merely executed.
_VERIFY_HINTS = (
    "test",
    "pytest",
    "jest",
    "vitest",
    "tsc",
    "typecheck",
    "type-check",
    "build",
    "lint",
    "eslint",
    "ruff",
    "mypy",
    "compile",
    "check",
)
_FAIL_HINTS = (
    "fail",
    "error",
    "traceback",
    "exception",
    "exit code 1",
    "non-zero",
    "npm err",
)
_PASS_HINTS = (
    "passed",
    "passing",
    "success",
    "succeeded",
    "clean",
    "exit code 0",
    "ok",
    "done",
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


def _as_str_list(value: Any) -> list[str]:
    """Coerce a JSON value to a list of non-empty strings (tolerant)."""

    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _dedupe_bounded(items: list[str], cap: int, max_chars: int) -> list[str]:
    """Collapse + truncate + de-dupe while preserving order, capped."""

    seen: dict[str, None] = {}
    for raw in items:
        text = _truncate(_collapse(str(raw)), max_chars)
        if not text:
            continue
        seen.setdefault(text, None)
        if len(seen) >= cap:
            break
    return list(seen.keys())


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
    commands: list[str] = field(default_factory=list)  # "cmd -> short result"
    verified: list[str] = field(default_factory=list)  # test/build/typecheck evidence
    next: str = ""  # the next safe action, when the turn named one

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
            files=_as_str_list(files),
            commands=_as_str_list(payload.get("commands")),
            verified=_as_str_list(payload.get("verified")),
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


_CODE_FILE_EXTENSIONS = (
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".py",
    ".json",
    ".css",
    ".scss",
    ".html",
    ".sh",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".sql",
    ".rs",
    ".go",
)


def _extract_file_mentions(text: str) -> list[str]:
    """Scan text for repo file paths mentioned in backticks or markdown diffs."""
    found: list[str] = []
    if not text:
        return found
    for match in re.finditer(r"`([^`\s]+\.[a-zA-Z0-9]{1,8})`", text):
        candidate = match.group(1).strip()
        if any(candidate.endswith(ext) for ext in _CODE_FILE_EXTENSIONS) and (
            "/" in candidate or "\\" in candidate
        ):
            found.append(candidate)
    for match in re.finditer(r"(?:Updated|Modified|Created|Edit(?:ed)?)\s+[`'\"]?([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]{1,8})[`'\"]?", text, re.IGNORECASE):
        candidate = match.group(1).strip()
        if any(candidate.endswith(ext) for ext in _CODE_FILE_EXTENSIONS):
            found.append(candidate)
    return found


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
    commands: list[str] | None = None,
    verified: list[str] | None = None,
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
    if not clean_files and did_source:
        extracted = _extract_file_mentions(did_source)
        clean_files = _dedupe_files(extracted)

    clean_commands = _dedupe_bounded(
        commands or [], _MAX_COMMANDS, _COMMAND_MAX_CHARS
    )
    clean_verified = _dedupe_bounded(
        verified or [], _MAX_VERIFIED, _VERIFY_MAX_CHARS
    )
    return TurnDigest(
        n=n,
        query_id=query_id,
        ts=ts,
        status=status or "done",
        user=user,
        did=did,
        files=clean_files,
        commands=clean_commands,
        verified=clean_verified,
        next=_extract_next(did_source),
    )


def _dedupe_files(files: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for raw in files:
        path = _truncate(_collapse(str(raw)), _FILE_MAX_CHARS)
        if not path:
            continue
        # Strip redundant file:/// prefix if present
        if path.startswith("file://"):
            path = path[7:]
        seen.setdefault(path, None)
        if len(seen) >= _MAX_FILES:
            break
    return list(seen.keys())


def extract_touched_files(tool_events: list[dict[str, Any]]) -> list[str]:
    """Best-effort list of file paths a run's tool events touched."""

    paths: list[str] = []
    for row in tool_events or []:
        if not isinstance(row, dict):
            continue
        args = row.get("arguments")
        if isinstance(args, dict):
            # Check patch_text / unified diff from DiffToolkit / apply_patch
            for patch_key in ("patch_text", "patch", "diff"):
                patch = args.get(patch_key)
                if isinstance(patch, str) and patch:
                    for match in re.finditer(r"^\+\+\+\s+[ab]/(.+)$", patch, re.MULTILINE):
                        paths.append(match.group(1).strip())
            for key in _FILE_ARG_KEYS:
                value = args.get(key)
                if isinstance(value, str) and value.strip():
                    paths.append(value.strip())
        res = row.get("result_summary")
        if isinstance(res, str) and res:
            for match in re.finditer(
                r"(?:Created|Updated|Modified|Wrote|Deleted)\s+file\s+[`'\"]?([^\s`'\"]+)[`'\"]?",
                res,
                re.IGNORECASE,
            ):
                paths.append(match.group(1).strip())
    return _dedupe_files(paths)


def _iter_command_events(
    tool_events: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    """Yield (command, result_summary) for each command-running tool event.

    Pure and tolerant: rows that are not dicts, have no command-running tool
    name, or carry no recognisable command string are skipped.
    """

    out: list[tuple[str, str]] = []
    for row in tool_events or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("tool_name") or "").lower()
        if not any(hint in name for hint in _CMD_TOOL_HINTS):
            continue
        args = row.get("arguments")
        if not isinstance(args, dict):
            continue
        command = ""
        for key in _CMD_ARG_KEYS:
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                command = value.strip()
                break
        if not command:
            continue
        result = str(row.get("result_summary") or "").strip()
        out.append((command, result))
    return out


def extract_commands(tool_events: list[dict[str, Any]]) -> list[str]:
    """Best-effort `command -> short result` lines for a run.

    Feeds the EXPORT handoff ("Commands run and results"), not the lean prompt
    view. A miss only means the handoff is slightly less specific.
    """

    lines = [
        f"{command} -> {_truncate(_collapse(result), _COMMAND_MAX_CHARS)}"
        if result
        else command
        for command, result in _iter_command_events(tool_events)
    ]
    return _dedupe_bounded(lines, _MAX_COMMANDS, _COMMAND_MAX_CHARS)


_ZERO_FAIL_RE = re.compile(r"\b0\s+(?:failed|failures|errors|failing)\b")


def _command_verdict(result: str) -> str:
    """Classify a command's result as passed / failed / ran (heuristic)."""

    text = (result or "").lower()
    if not text:
        return "ran"
    # A explicit zero-failure count wins, e.g. "14 passed, 0 failed".
    if _ZERO_FAIL_RE.search(text) or "no failures" in text or "no errors" in text:
        return "passed"
    if any(hint in text for hint in _FAIL_HINTS):
        return "failed"
    if any(hint in text for hint in _PASS_HINTS):
        return "passed"
    return "ran"


def extract_verification(tool_events: list[dict[str, Any]]) -> list[str]:
    """Best-effort acceptance evidence: test/build/lint/typecheck commands.

    Only commands whose text looks like a verification step are kept, paired
    with a passed/failed verdict so the next session knows what was actually
    checked.
    """

    lines: list[str] = []
    for command, result in _iter_command_events(tool_events):
        if not any(hint in command.lower() for hint in _VERIFY_HINTS):
            continue
        lines.append(
            f"{_truncate(_collapse(command), _VERIFY_MAX_CHARS)}"
            f" -> {_command_verdict(result)}"
        )
    return _dedupe_bounded(lines, _MAX_VERIFIED, _VERIFY_MAX_CHARS)


def is_digest_relevant_tool(tool_name: str) -> bool:
    """True when a tool call can enrich a turn digest.

    Only file-writing and command-running tools feed the EXPORT handoff (files
    changed, commands run, verification evidence). Capturing the rest (reads,
    searches, browser) would grow ``tool_events.jsonl`` and add work to the hot
    tool path for no gain, so the agent filters with this predicate before it
    records a ToolEvent.
    """

    name = (tool_name or "").lower()
    if not name:
        return False
    return any(h in name for h in _FILE_TOOL_HINTS) or any(
        h in name for h in _CMD_TOOL_HINTS
    )


_NEXT_LINE_RE = re.compile(
    r"(?:next(?:\s+safe)?\s+(?:step|steps|action|actions)|to\s+proceed|next\s+up|what's\s+next|next\s+phase)\s*[:\-]\s*(.+)",
    re.IGNORECASE,
)


def _extract_next(text: str) -> str:
    """Pull a "Next step: ..." / "Next safe action: ..." line out of a result."""
    if not text:
        return ""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        match = _NEXT_LINE_RE.search(line)
        if match:
            extracted = match.group(1).strip()
            # If the header line has no body (e.g. "Next steps:"), take following bullets
            if not extracted and i + 1 < len(lines):
                next_bullets = []
                for j in range(i + 1, min(i + 4, len(lines))):
                    l = lines[j].strip()
                    if l.startswith(("-", "*", "1.", "2.", "3.")):
                        next_bullets.append(l.lstrip("-*123456789. "))
                    elif not l:
                        continue
                    else:
                        break
                if next_bullets:
                    return _truncate("; ".join(next_bullets), _NEXT_MAX_CHARS)
            return _truncate(_collapse(extracted), _NEXT_MAX_CHARS)
    return ""


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
            commands=digest.commands or turns[existing_idx].commands,
            verified=digest.verified or turns[existing_idx].verified,
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
                commands=digest.commands,
                verified=digest.verified,
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


_CONVERSATIONAL_RE = re.compile(
    r"^\s*(b|ok|okay|yes|yea|yeah|sure|proceed|continue|go|done|great|thanks|ty|lol|hmm|hi|hello|hey)\s*[.!?]*\s*$",
    re.IGNORECASE,
)


def _looks_conversational(text: str) -> bool:
    """Return True when the user message is a short filler (not a real objective)."""
    if not text or len(text.strip()) < 2:
        return True
    return bool(_CONVERSATIONAL_RE.match(text.strip()))


def handoff_sections(summary: RollingSummary) -> dict[str, Any]:
    """Structured view of a Project's summary for the EXPORT handoff.

    Deterministic projection of the stored turn digests into the sections a
    real agent handoff needs (objective, status, files, commands run,
    verification, blockers, next safe action). No model call, so it is safe to
    call from the read-only handoff endpoint.
    """

    turns = summary.turns
    latest = turns[-1] if turns else None

    # Find the primary substantive objective, bypassing brief greetings
    objective = ""
    for turn in turns:
        if turn.user and not _looks_conversational(turn.user):
            objective = turn.user
            break
    if not objective and turns:
        objective = turns[0].user

    def _union(attr: str) -> list[str]:
        seen: dict[str, None] = {}
        for turn in turns:
            for item in getattr(turn, attr, None) or []:
                seen.setdefault(str(item), None)
        return list(seen.keys())

    status_line = ""
    if latest:
        status_tag = latest.status or "completed"
        did_text = (latest.did or "").strip()
        if did_text and did_text != "(no result recorded)":
            status_line = f"Turn {latest.n} ({status_tag}): {did_text}"
        elif latest.user:
            # No assistant result recorded; summarise from the user's last request
            status_line = f"Turn {latest.n} ({status_tag}): re: {_truncate(_collapse(latest.user), 120)}"
        else:
            status_line = f"Turn {latest.n} ({status_tag})"

    return {
        "objective": objective,
        "status": latest.status if latest else "",
        "status_line": status_line,
        "turn_count": summary.turn_count,
        "updated_at": summary.updated_at,
        "rolling": summary.rolling,
        "files": _union("files"),
        "commands": _union("commands"),
        "verified": _union("verified"),
        "blockers": [
            f"Turn {t.n} ({t.status}): {t.did}"
            for t in turns
            if t.status in ("failed", "cancelled")
        ],
        "next_action": next((t.next for t in reversed(turns) if t.next), ""),
        "timeline": [
            {
                "n": t.n,
                "status": t.status,
                "user": t.user,
                "did": t.did,
                "files": list(t.files),
                "commands": list(t.commands),
                "verified": list(t.verified),
                "next": t.next,
            }
            for t in turns
        ],
    }


def render_handoff_md(summary: RollingSummary) -> str:
    """Render the full structured handoff document (deterministic).

    This is the EXPORT view: richer than `render_md` (which stays lean for
    prompt injection) because the handoff is written once and read by a fresh
    session, so it can afford commands, verification and the next action.
    """

    import datetime

    s = handoff_sections(summary)
    lines: list[str] = []

    # --- Document metadata block ---
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines += [
        "---",
        f"generated: {now_iso}",
        f"turns: {s['turn_count']}",
    ]
    if s["updated_at"]:
        lines.append(f"last_active: {s['updated_at']}")
    if s["status"]:
        lines.append(f"status: {s['status']}")
    lines += ["---", ""]

    if s["objective"]:
        lines += ["### Objective", "", s["objective"], ""]

    if s["status_line"]:
        lines += ["### Current status", "", s["status_line"], ""]

    if s["files"]:
        lines += ["### Files changed", ""]
        lines += [f"- `{f}`" for f in s["files"]]
        lines.append("")

    if s["commands"]:
        lines += ["### Commands run and results", ""]
        lines += [f"- `{c}`" for c in s["commands"]]
        lines.append("")

    if s["verified"]:
        lines += ["### Verified", ""]
        lines += [f"- {v}" for v in s["verified"]]
        lines.append("")

    if s["blockers"]:
        lines += ["### Blockers", ""]
        lines += [f"- {b}" for b in s["blockers"]]
        lines.append("")

    if s.get("rolling"):
        lines += [
            "### Earlier context (folded turns)",
            "",
            _truncate(_collapse(s["rolling"]), _ROLLING_MAX_CHARS),
            "",
        ]

    if s["timeline"]:
        lines += ["### What happened (turn by turn)", ""]
        for t in s["timeline"]:
            icon = "✅" if t["status"] == "done" else ("❌" if t["status"] == "failed" else "⏸️")
            lines.append(f"**Turn {t['n']}** {icon}")
            lines.append(f"- **User:** {t['user']}")
            if t["did"] and t["did"] != "(no result recorded)":
                lines.append(f"- **Did:** {t['did']}")
            if t["files"]:
                for fp in t["files"]:
                    lines.append(f"  - `{fp}`")
            if t["verified"]:
                lines.append(f"- **Verified:** {'; '.join(t['verified'])}")
            if t["next"]:
                lines.append(f"- **Next:** {t['next']}")
            lines.append("")

    if s["next_action"]:
        lines += ["### Next safe action", "", s["next_action"], ""]

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

    Handles the common case where the user sends several rapid messages before
    the agent replies (e.g. "continue", "b", "yea proceed"): those runs have a
    user event but no assistant event. We carry the MOST RECENT assistant reply
    forward so the `did` field is never blank for them.
    """

    max_turns = max_turns or max(20, keep_turns() * 4)
    by_run: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for event in events or []:
        run_id = str(getattr(event, "run_id", "") or "")
        role = str(getattr(event, "role", "") or "")
        content = getattr(event, "content", "") or ""
        if not run_id or role not in ("user", "assistant", "agent"):
            continue
        if run_id not in by_run:
            by_run[run_id] = {}
            order.append(run_id)
        # Keep the first user message and the last assistant message per run.
        if role == "user" and content and not by_run[run_id].get("user"):
            by_run[run_id]["user"] = content
        elif role in ("assistant", "agent") and content:
            by_run[run_id]["assistant"] = content

    summary = RollingSummary(project_id=project_id, updated_at=updated_at)
    last_assistant: str = ""  # carry forward across user-only runs
    for run_id in order[-max_turns:]:
        row = by_run[run_id]
        if not row.get("user") and not row.get("assistant"):
            continue
        assistant_text = row.get("assistant", "")
        if assistant_text:
            last_assistant = assistant_text
        elif last_assistant:
            # This run had no assistant reply; annotate with the latest known response
            assistant_text = last_assistant
        digest = build_turn_digest(
            query_id=run_id,
            status="done",
            user_prompt=row.get("user", ""),
            final_result=assistant_text,
            ts="",
        )
        summary = merge(summary, digest)
    summary.updated_at = updated_at
    return summary


def load(store: Any, user_key: str, space_id: str, project_id: str) -> RollingSummary | None:
    """Read the structured summary for a Project (None when absent/corrupt)."""

    try:
        payload = store.read_project_summary_json(user_key, space_id, project_id)
        if payload is not None:
            summary = RollingSummary.from_dict(payload)
            if summary and summary.turns:
                return summary
    except Exception:  # noqa: BLE001 — best-effort read
        logger.debug("rolling_summary.load failed", exc_info=True)

    # Dynamic fallback: if no summary JSON was finalized yet, synthesize from conversation history
    try:
        events = store.read_conversation_tail(
            user_key, space_id, project_id, limit=200
        )
        if events:
            return backfill_from_conversation(events, project_id=project_id)
    except Exception:
        logger.debug(
            "rolling_summary.load fallback from conversation failed",
            exc_info=True,
        )
    return None


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
