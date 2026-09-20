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

"""Hybrid conversational memory schema (``hybrid_memory.md`` §3, §7, §10, §14).

Four representations, kept strictly separate:

- **Raw messages** are authoritative and untouched; they live in the existing
  ``conversation.jsonl`` (``ConversationEvent``). Nothing here rewrites them.
- **Episodes** (§7) are independent, non-recursive summaries of a turn range
  with ``source_message_ids`` back-pointers.
- **Structured memory** (§10) holds versioned key/value records with explicit
  ``status`` so current state is distinguishable from superseded history.
- **Working memory** (§14) describes the task in flight.

Every record is a flat, JSON-serializable dataclass with
``to_dict``/``from_dict`` so the store can round-trip without schema drift.
``from_dict`` is deliberately tolerant: unknown keys are dropped and malformed
rows return ``None`` rather than raising, because a corrupt sidecar must never
break a chat turn.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION: int = 1

MEMORY_TYPES = ("fact", "preference", "decision", "constraint", "goal")
MEMORY_STATUSES = ("active", "superseded", "deleted")

# Explicit memory scope (``memory-cross-session-feature.md`` §2, §6, §23). Scope
# is what lets a brand-new thread tell "this belongs to this one chat" apart from
# "this is a durable user-level fact" and "this belongs to a recurring project".
SCOPE_GLOBAL = "global"
SCOPE_PROJECT = "project"
SCOPE_CONVERSATION = "conversation"
MEMORY_SCOPES = (SCOPE_GLOBAL, SCOPE_PROJECT, SCOPE_CONVERSATION)

# Retrieval escalation levels (§22).
LEVEL_RECENT = 1
LEVEL_MEMORY = 2
LEVEL_EPISODES = 3
LEVEL_EXACT = 4
LEVEL_BROAD = 5


def _clean(cls: type, payload: Any) -> dict[str, Any] | None:
    """Drop unknown keys and require a mapping; None on anything else."""

    if not isinstance(payload, dict):
        return None
    known = {f for f in getattr(cls, "__dataclass_fields__", {})}
    return {k: v for k, v in payload.items() if k in known}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if isinstance(v, (str, int, float))]


@dataclass
class Episode:
    """A coherent historical segment of a conversation (§7)."""

    id: str
    conversation_id: str
    start_turn: int
    end_turn: int
    title: str
    summary: str
    source_message_ids: list[str] = field(default_factory=list)
    topic: str = ""
    importance: float = 0.5
    created_at: str = ""
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Any) -> Episode | None:
        cleaned = _clean(cls, payload)
        if cleaned is None:
            return None
        cleaned["source_message_ids"] = _as_str_list(
            cleaned.get("source_message_ids")
        )
        try:
            return cls(**cleaned)
        except (TypeError, ValueError):
            return None

    def source_text(self) -> str:
        """Text indexed for semantic retrieval: title + topic + summary."""

        return " ".join(p for p in (self.title, self.topic, self.summary) if p)


@dataclass
class StructuredMemory:
    """A versioned durable fact/preference/decision/constraint/goal (§10-11).

    ``scope_type``/``scope_id`` make the memory's reach explicit (§2, §6): a
    ``global`` record is user-level and recoverable from any thread, a
    ``project`` record spans the threads of one project (``scope_id`` = the
    project id), and a ``conversation`` record stays in its own thread
    (``scope_id`` = the conversation id). ``conversation_id`` is retained as
    provenance: it names the thread the record was first learned in, so a
    cross-session hit can be traced back to the conversation that produced it
    (§4, §31).
    """

    id: str
    conversation_id: str
    type: str
    key: str
    value: str
    status: str = "active"
    version: int = 1
    confidence: float = 0.7
    source_message_ids: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    scope_type: str = SCOPE_PROJECT
    scope_id: str = ""
    user_id: str = ""
    importance: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Any) -> StructuredMemory | None:
        cleaned = _clean(cls, payload)
        if cleaned is None:
            return None
        cleaned["source_message_ids"] = _as_str_list(
            cleaned.get("source_message_ids")
        )
        try:
            return cls(**cleaned)
        except (TypeError, ValueError):
            return None


@dataclass
class MemoryOp:
    """A proposed mutation the application validates before applying (§12).

    The extractor never touches storage directly; it proposes ops and
    :mod:`app.memory.hybrid.storage` decides what is valid.
    """

    op: str  # UPSERT | SUPERSEDE | DELETE | MERGE
    type: str = ""
    key: str = ""
    value: str = ""
    memory_id: str = ""
    reason: str = ""
    confidence: float = 0.7
    # How much the memory matters for retrieval ranking (§17). The proposal
    # carries it so the deterministic mutation gate can stamp the durable
    # record without re-deriving it from the conversation.
    importance: float = 0.5
    source_message_ids: list[str] = field(default_factory=list)
    # The extraction layer classifies scope explicitly (§23): "I prefer
    # TypeScript" is proposed as ``global``, "for this one prototype use SQLite"
    # as ``conversation``. Empty means "decide deterministically at write time"
    # (see ``app.memory.hybrid.scope.resolve_op_scope``); the write path fills
    # ``scope_id``/``user_id`` from the chosen scope, so proposals never need to
    # know the user/project/conversation ids themselves.
    scope_type: str = ""
    scope_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Any) -> MemoryOp | None:
        cleaned = _clean(cls, payload)
        if cleaned is None:
            return None
        cleaned["source_message_ids"] = _as_str_list(
            cleaned.get("source_message_ids")
        )
        try:
            return cls(**cleaned)
        except (TypeError, ValueError):
            return None


@dataclass
class EpisodeDraft:
    """The model's *proposed* semantic summary of a message slice (§30).

    A draft is never stored on its own. The engine merges it onto the
    deterministically-bounded :class:`Episode` (which keeps the id, turn range
    and source links), so boundaries stay application-controlled even when the
    prose comes from a model. Keeping the two types separate is what lets the
    deterministic planner double as the validator of the model's output.
    """

    title: str = ""
    summary: str = ""
    objective: str = ""
    topic: str = ""
    importance: float = 0.5
    decisions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Any) -> EpisodeDraft | None:
        cleaned = _clean(cls, payload)
        if cleaned is None:
            return None
        for name in ("title", "summary", "objective", "topic"):
            if cleaned.get(name) is None:
                cleaned[name] = ""
        if cleaned.get("importance") is None:
            cleaned["importance"] = 0.5
        cleaned["decisions"] = _as_str_list(cleaned.get("decisions"))
        try:
            return cls(**cleaned)
        except (TypeError, ValueError):
            return None


@dataclass
class ExtractionResult:
    """One model extraction pass: an episode draft + proposed memory ops.

    ``research1.md`` asks for these two to stay separate because they have
    different purposes -- the episode is human-readable historical compression,
    the ops are machine-actionable state changes that must survive validation.
    Splitting them keeps both debuggable instead of hiding them in one opaque
    model blob.
    """

    episode: EpisodeDraft = field(default_factory=EpisodeDraft)
    memory_ops: list[MemoryOp] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode": self.episode.to_dict(),
            "memory_ops": [op.to_dict() for op in self.memory_ops],
        }

    @classmethod
    def from_dict(cls, payload: Any) -> ExtractionResult | None:
        if not isinstance(payload, dict):
            return None
        episode = EpisodeDraft.from_dict(payload.get("episode")) or EpisodeDraft()
        raw_ops = payload.get("memory_ops") or payload.get("memoryOps")
        ops: list[MemoryOp] = []
        for row in raw_ops if isinstance(raw_ops, list) else []:
            op = MemoryOp.from_dict(row)
            if op is not None:
                ops.append(op)
        return cls(episode=episode, memory_ops=ops)


@dataclass
class WorkingMemory:
    """The agent's current-task state, separate from historical memory (§14)."""

    conversation_id: str
    current_task: str = ""
    current_goal: str = ""
    decisions: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    current_status: str = ""
    next_step: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Any) -> WorkingMemory | None:
        cleaned = _clean(cls, payload)
        if cleaned is None:
            return None
        for field_name in ("decisions", "constraints", "open_questions"):
            cleaned[field_name] = _as_str_list(cleaned.get(field_name))
        try:
            return cls(**cleaned)
        except (TypeError, ValueError):
            return None

    def is_empty(self) -> bool:
        return not any(
            [
                self.current_task,
                self.current_goal,
                self.decisions,
                self.constraints,
                self.open_questions,
                self.current_status,
                self.next_step,
            ]
        )


@dataclass
class RetrievalPlan:
    """What the cheap router decided to run this turn (§18, §22)."""

    level: int = LEVEL_RECENT
    use_recent: bool = True
    use_memory: bool = False
    use_semantic: bool = False
    use_lexical: bool = False
    use_exact: bool = False
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def describe(self) -> str:
        flags = [
            name
            for name, on in (
                ("recent", self.use_recent),
                ("memory", self.use_memory),
                ("semantic", self.use_semantic),
                ("lexical", self.use_lexical),
                ("exact", self.use_exact),
            )
            if on
        ]
        return f"level={self.level} ({', '.join(flags) or 'none'})"


@dataclass
class RetrievedItem:
    """One ranked candidate handed to the context builder."""

    kind: str  # "episode" | "message" | "memory" | "working"
    id: str
    text: str
    score: float = 0.0
    source_message_ids: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    turn: int | None = None
    status: str = ""
    scope: str = ""  # "global" | "project" | "conversation" (§2)
    origin_project_id: str = ""  # thread the evidence came from (§31)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalResult:
    """Everything retrieval produced, plus observability metadata (§43)."""

    plan: RetrievalPlan
    episodes: list[RetrievedItem] = field(default_factory=list)
    messages: list[RetrievedItem] = field(default_factory=list)
    active_memories: list[RetrievedItem] = field(default_factory=list)
    superseded_memories: list[RetrievedItem] = field(default_factory=list)
    working_memory: WorkingMemory | None = None
    evidence_found: str = "none"  # "exact" | "approximate" | "none"
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "episodes": [e.to_dict() for e in self.episodes],
            "messages": [m.to_dict() for m in self.messages],
            "active_memories": [m.to_dict() for m in self.active_memories],
            "superseded_memories": [
                m.to_dict() for m in self.superseded_memories
            ],
            "working_memory": (
                self.working_memory.to_dict() if self.working_memory else None
            ),
            "evidence_found": self.evidence_found,
            "diagnostics": self.diagnostics,
        }


def dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)
