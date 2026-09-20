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

"""Filesystem storage for the hybrid memory sidecars (§10-13, §31-32).

Lives alongside the existing ``ConversationEvent`` transcript under the same
Project directory:

    <project>/conversation.jsonl   raw messages (authoritative, untouched)
    <project>/episodes.json        independent episode summaries (§7)
    <project>/memories.json        versioned structured memory (§10-11)
    <project>/working_memory.json  current-task state (§14)
    <project>/hybrid_meta.json     episode coverage watermark
    <project>/retrieval_log.jsonl  observability (§43)
    <project>/extraction_log.jsonl model-vs-deterministic extraction comparison

The store owns *mutation policy*: the extractor only proposes
:class:`MemoryOp` objects, and :meth:`HybridStore.apply_ops` validates and
applies them, preserving history via versioning + supersession (§11-12). Every
read tolerates a missing/corrupt file. Writes are atomic and lock-guarded.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from app.memory.hybrid import canonical
from app.memory.hybrid.schema import (
    MEMORY_TYPES,
    SCOPE_PROJECT,
    Episode,
    MemoryOp,
    StructuredMemory,
    WorkingMemory,
)
from app.memory.local_store import (
    LocalMemoryStore,
    append_jsonl_file,
    read_json_file,
    update_json_file,
    write_json_file,
)

logger = logging.getLogger("memory.hybrid.storage")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class HybridStore:
    """Read/write the hybrid sidecars for one Project, given a LocalMemoryStore."""

    def __init__(self, store: LocalMemoryStore) -> None:
        self._store = store

    @property
    def base(self) -> LocalMemoryStore:
        return self._store

    # ----- Paths -----

    def _dir(self, user_key: str, space_id: str, project_id: str) -> Path:
        """Directory the sidecars live in.

        Overridden by :class:`~app.memory.hybrid.scope.GlobalMemoryStore` to point
        at the user root instead of a project dir, so user-level ("global") memory
        can reuse the same records, validation and mutation gate as project
        memory (§2, §23).
        """

        return self._store.project_path(user_key, space_id, project_id)

    def _path(self, user_key: str, space_id: str, project_id: str, name: str) -> Path:
        return self._dir(user_key, space_id, project_id) / name

    # ----- Episodes -----

    def read_episodes(
        self, user_key: str, space_id: str, project_id: str
    ) -> list[Episode]:
        payload = read_json_file(
            self._path(user_key, space_id, project_id, "episodes.json")
        )
        rows = payload.get("episodes") if isinstance(payload, dict) else None
        out: list[Episode] = []
        for row in rows if isinstance(rows, list) else []:
            episode = Episode.from_dict(row)
            if episode is not None:
                out.append(episode)
        out.sort(key=lambda e: (e.start_turn, e.end_turn))
        return out

    def write_episodes(
        self,
        user_key: str,
        space_id: str,
        project_id: str,
        episodes: list[Episode],
    ) -> None:
        path = self._path(user_key, space_id, project_id, "episodes.json")
        write_json_file(path, {"episodes": [e.to_dict() for e in episodes]})

    def append_episodes(
        self,
        user_key: str,
        space_id: str,
        project_id: str,
        new_episodes: list[Episode],
    ) -> list[Episode]:
        """Add episodes, deduping by id. Returns the full sorted list."""

        if not new_episodes:
            return self.read_episodes(user_key, space_id, project_id)

        def _mutate(payload: Any) -> dict[str, Any]:
            rows = payload.get("episodes") if isinstance(payload, dict) else None
            existing: list[Episode] = []
            for row in rows if isinstance(rows, list) else []:
                episode = Episode.from_dict(row)
                if episode is not None:
                    existing.append(episode)
            by_id = {e.id: e for e in existing}
            for episode in new_episodes:
                by_id[episode.id] = episode
            return {"episodes": [e.to_dict() for e in by_id.values()]}

        updated = update_json_file(
            self._path(user_key, space_id, project_id, "episodes.json"), _mutate
        )
        rows = updated.get("episodes") if isinstance(updated, dict) else []
        out = [
            e for e in (Episode.from_dict(r) for r in rows or []) if e is not None
        ]
        out.sort(key=lambda e: (e.start_turn, e.end_turn))
        return out

    # ----- Memories -----

    def read_memories(
        self,
        user_key: str,
        space_id: str,
        project_id: str,
        *,
        status: str | None = None,
    ) -> list[StructuredMemory]:
        payload = read_json_file(
            self._path(user_key, space_id, project_id, "memories.json")
        )
        rows = payload.get("memories") if isinstance(payload, dict) else None
        out: list[StructuredMemory] = []
        for row in rows if isinstance(rows, list) else []:
            memory = StructuredMemory.from_dict(row)
            if memory is None:
                continue
            if status is not None and memory.status != status:
                continue
            out.append(memory)
        return out

    def read_active_memories(
        self, user_key: str, space_id: str, project_id: str
    ) -> list[StructuredMemory]:
        return self.read_memories(
            user_key, space_id, project_id, status="active"
        )

    def _write_memories(
        self,
        user_key: str,
        space_id: str,
        project_id: str,
        memories: list[StructuredMemory],
    ) -> None:
        path = self._path(user_key, space_id, project_id, "memories.json")
        write_json_file(path, {"memories": [m.to_dict() for m in memories]})

    def _mutate_memories(
        self,
        user_key: str,
        space_id: str,
        project_id: str,
        mutator: Any,
    ) -> list[StructuredMemory]:
        def _wrap(payload: Any) -> dict[str, Any]:
            rows = payload.get("memories") if isinstance(payload, dict) else None
            existing: list[StructuredMemory] = []
            for row in rows if isinstance(rows, list) else []:
                memory = StructuredMemory.from_dict(row)
                if memory is not None:
                    existing.append(memory)
            result = mutator(existing)
            return {"memories": [m.to_dict() for m in result]}

        updated = update_json_file(
            self._path(user_key, space_id, project_id, "memories.json"), _wrap
        )
        rows = updated.get("memories") if isinstance(updated, dict) else []
        return [
            m
            for m in (StructuredMemory.from_dict(r) for r in rows or [])
            if m is not None
        ]

    def apply_ops(
        self,
        user_key: str,
        space_id: str,
        project_id: str,
        ops: list[MemoryOp],
        *,
        conversation_id: str,
        now: str,
        valid_source_ids: set[str] | None = None,
        scope_type: str = SCOPE_PROJECT,
        scope_id: str = "",
        user_id: str = "",
    ) -> list[StructuredMemory]:
        """Validate + apply a batch of proposed ops (§12).

        UPSERT of an existing ``(type, key)`` with a *different* value supersedes
        the old record and writes a new version; identical values are merged
        idempotently. SUPERSEDE/DELETE/MERGE target a specific ``memory_id`` and
        are dropped when the id is unknown (never destroy what we cannot find).

        ``valid_source_ids`` is the set of message ids that legitimately exist in
        this conversation. When the caller supplies it, an op whose
        ``source_message_ids`` are empty or point outside that set is dropped --
        this is the "``msg_219`` exists / belongs to conversation X" check from
        ``research1.md``, the guardrail that stops a model from inventing a
        memory with no evidence. When it is ``None`` (callers that do not load
        the transcript) the provenance check is skipped, so existing behaviour is
        unchanged.
        """

        if not ops:
            return []

        def _has_provenance(op: MemoryOp) -> bool:
            if valid_source_ids is None:
                return True
            return any(
                source_id in valid_source_ids
                for source_id in op.source_message_ids
            )

        def _is_relevant(op: MemoryOp) -> bool:
            name = (op.op or "").upper()
            if name == "UPSERT":
                # UPSERTs must carry a known memory type; targeted ops address a
                # record by id and legitimately have no type of their own.
                if (op.type or "").lower() not in MEMORY_TYPES:
                    return False
            elif name not in {"SUPERSEDE", "DELETE", "MERGE"}:
                return False
            return _has_provenance(op)

        relevant = [op for op in ops if _is_relevant(op)]

        def _mutator(memories: list[StructuredMemory]) -> list[StructuredMemory]:
            by_id = {m.id: m for m in memories}
            for op in relevant:
                name = (op.op or "").upper()
                if name == "UPSERT":
                    self._apply_upsert(
                        by_id,
                        op,
                        conversation_id=conversation_id,
                        now=now,
                        scope_type=scope_type,
                        scope_id=scope_id,
                        user_id=user_id,
                    )
                elif name in {"SUPERSEDE", "DELETE", "MERGE"}:
                    self._apply_targeted(by_id, op, name, now=now)
                else:
                    logger.debug("hybrid: ignoring unknown op %r", op.op)
            return list(by_id.values())

        return self._mutate_memories(
            user_key, space_id, project_id, _mutator
        )

    @staticmethod
    def _existing_active(
        by_id: dict[str, StructuredMemory], memory_type: str, key: str
    ) -> StructuredMemory | None:
        wanted = canonical.identity(memory_type, key)
        for memory in by_id.values():
            if memory.status != "active":
                continue
            if canonical.identity(memory.type, memory.key) == wanted:
                return memory
        return None

    def _apply_upsert(
        self,
        by_id: dict[str, StructuredMemory],
        op: MemoryOp,
        *,
        conversation_id: str,
        now: str,
        scope_type: str = SCOPE_PROJECT,
        scope_id: str = "",
        user_id: str = "",
    ) -> None:
        value = (op.value or "").strip()
        if not value:
            return
        key = canonical.normalize_key(op.key) or canonical.normalize_key(op.type)
        existing = self._existing_active(by_id, op.type, key)
        sources = list(op.source_message_ids)
        # A brand-new record inherits the scope of the write (§2, §6, §23): a
        # global write lands user-level, a project write lands project-level,
        # and a conversation write stays in its thread. ``origin_project_id`` is
        # kept on the record so a cross-session hit can be traced back to the
        # conversation that first produced it (§4, §31).
        stamp = {
            "scope_type": scope_type,
            "scope_id": scope_id,
            "user_id": user_id,
            "importance": max(existing.importance if existing else 0.0, op.importance),
        }
        if existing is None:
            record = StructuredMemory(
                id=_new_id("mem"),
                conversation_id=conversation_id,
                type=op.type,
                key=key,
                value=value,
                status="active",
                version=1,
                confidence=op.confidence,
                source_message_ids=sources,
                created_at=now,
                updated_at=now,
                **stamp,
            )
            by_id[record.id] = record
            return
        if existing.value.strip().lower() == value.lower():
            # Idempotent re-statement: refresh provenance + timestamps only.
            merged_sources = list(
                dict.fromkeys([*existing.source_message_ids, *sources])
            )
            by_id[existing.id] = StructuredMemory(
                **{
                    **existing.to_dict(),
                    "source_message_ids": merged_sources,
                    "confidence": max(existing.confidence, op.confidence),
                    "updated_at": now,
                }
            )
            return
        # Value changed -> preserve history, create the next version (§11).
        by_id[existing.id] = StructuredMemory(
            **{
                **existing.to_dict(),
                "status": "superseded",
                "updated_at": now,
            }
        )
        record = StructuredMemory(
            id=_new_id("mem"),
            conversation_id=conversation_id,
            type=op.type,
            key=key,
            value=value,
            status="active",
            version=existing.version + 1,
            confidence=op.confidence,
            source_message_ids=sources,
            created_at=now,
            updated_at=now,
            **stamp,
        )
        by_id[record.id] = record

    @staticmethod
    def _apply_targeted(
        by_id: dict[str, StructuredMemory],
        op: MemoryOp,
        name: str,
        *,
        now: str,
    ) -> None:
        target = by_id.get(op.memory_id)
        if target is None:
            return
        if name == "SUPERSEDE":
            by_id[target.id] = StructuredMemory(
                **{**target.to_dict(), "status": "superseded", "updated_at": now}
            )
        elif name == "DELETE":
            by_id[target.id] = StructuredMemory(
                **{**target.to_dict(), "status": "deleted", "updated_at": now}
            )
        elif name == "MERGE":
            addition = (op.value or "").strip()
            if addition and addition.lower() not in target.value.lower():
                combined = f"{target.value.rstrip()} {addition}".strip()
                by_id[target.id] = StructuredMemory(
                    **{
                        **target.to_dict(),
                        "value": combined,
                        "source_message_ids": list(
                            dict.fromkeys(
                                [
                                    *target.source_message_ids,
                                    *op.source_message_ids,
                                ]
                            )
                        ),
                        "updated_at": now,
                    }
                )

    # ----- Working memory -----

    def read_working_memory(
        self, user_key: str, space_id: str, project_id: str
    ) -> WorkingMemory | None:
        payload = read_json_file(
            self._path(user_key, space_id, project_id, "working_memory.json")
        )
        return WorkingMemory.from_dict(payload)

    def write_working_memory(
        self,
        user_key: str,
        space_id: str,
        project_id: str,
        memory: WorkingMemory,
    ) -> None:
        path = self._path(user_key, space_id, project_id, "working_memory.json")
        write_json_file(path, memory.to_dict())

    # ----- Episode coverage watermark -----

    def read_covered_through_turn(
        self, user_key: str, space_id: str, project_id: str
    ) -> int:
        payload = read_json_file(
            self._path(user_key, space_id, project_id, "hybrid_meta.json")
        )
        if not isinstance(payload, dict):
            return 0
        try:
            return int(payload.get("covered_through_turn") or 0)
        except (TypeError, ValueError):
            return 0

    def write_covered_through_turn(
        self,
        user_key: str,
        space_id: str,
        project_id: str,
        turn: int,
        *,
        now: str,
    ) -> None:
        def _mutate(payload: Any) -> dict[str, Any]:
            base = payload if isinstance(payload, dict) else {}
            return {
                **base,
                "covered_through_turn": int(turn),
                "updated_at": now,
            }

        update_json_file(
            self._path(user_key, space_id, project_id, "hybrid_meta.json"),
            _mutate,
        )

    # ----- Observability log (§43) -----

    def append_retrieval_log(
        self, user_key: str, space_id: str, project_id: str, payload: dict[str, Any]
    ) -> None:
        try:
            append_jsonl_file(
                self._path(
                    user_key, space_id, project_id, "retrieval_log.jsonl"
                ),
                payload,
            )
        except Exception:  # noqa: BLE001 - observability is best-effort
            logger.debug("hybrid: retrieval log append failed", exc_info=True)

    def append_extraction_log(
        self, user_key: str, space_id: str, project_id: str, payload: dict[str, Any]
    ) -> None:
        """Record one model-vs-deterministic extraction comparison.

        This is the evaluation surface for the optional LLM extraction pass: in
        shadow mode it is the ONLY thing the model path produces, so the two
        outputs can be compared (episode quality, memory precision, false
        memories, missed decisions, incorrect supersedes) before the model is
        allowed to write. Best-effort: a logging failure never affects a turn.
        """

        try:
            append_jsonl_file(
                self._path(
                    user_key, space_id, project_id, "extraction_log.jsonl"
                ),
                payload,
            )
        except Exception:  # noqa: BLE001 - observability is best-effort
            logger.debug("hybrid: extraction log append failed", exc_info=True)
