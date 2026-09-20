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

"""Semantic (vector) index for episodes and structured memory (§5, §16, §30-31).

Two collections, both on-device MiniLM embeddings, both fail-soft:

    eigent_episodes   episode summaries (§7, §10)
    eigent_memories   structured memory records (§6, §11)

Chroma is an **index, never the application-level authority** (§31): every
document carries the durable application id plus provenance metadata, so a hit
maps back to the ``memories.json`` / ``episodes.json`` record and from there to
the exact source messages. Deleting or rebuilding a collection therefore never
loses a memory -- it only loses the ability to *find* it semantically until the
next reindex.

Metadata is what makes §16 filtering (``userId`` / ``projectId`` /
``scopeType`` / ``status``) possible. Chroma metadata must be scalar, so
``sourceMessageIds`` is stored as a JSON string (with a count alongside for
cheap filtering).
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from app.memory.hybrid.schema import Episode, StructuredMemory

logger = logging.getLogger("memory.hybrid.vector")

_EPISODE_COLLECTION = "eigent_episodes"
_MEMORY_COLLECTION = "eigent_memories"

_lock = threading.Lock()
_collections: dict[str, Any] = {}
_disabled = False


def _root() -> Path:
    return Path.home() / ".undisclosed" / "memory" / "semantic"


def _get_collection(name: str) -> Any | None:
    """Lazily open one on-disk collection. None when unavailable."""

    global _disabled
    cached = _collections.get(name)
    if cached is not None:
        return cached
    if _disabled:
        return None
    with _lock:
        cached = _collections.get(name)
        if cached is not None:
            return cached
        if _disabled:
            return None
        try:
            import chromadb

            root = _root()
            root.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(root))
            collection = client.get_or_create_collection(name)
            _collections[name] = collection
            logger.info("hybrid vector %s ready at %s", name, root)
            return collection
        except Exception as exc:  # noqa: BLE001 - fail soft
            logger.warning("hybrid vector index disabled: %s", exc)
            _disabled = True
            return None


def _encode_ids(ids: Any) -> str:
    """Chroma metadata is scalar; keep source ids losslessly as a JSON string."""

    return json.dumps([str(i) for i in (ids or [])], ensure_ascii=False)


def _where(clauses: list[tuple[str, Any]]) -> dict[str, Any] | None:
    """Build a chroma ``where`` filter from non-empty equality clauses."""

    present = [
        {key: value} for key, value in clauses if value not in (None, "")
    ]
    if not present:
        return None
    if len(present) == 1:
        return present[0]
    return {"$and": present}


def _similarity(distance: Any) -> float:
    try:
        return 1.0 / (1.0 + float(distance))
    except (TypeError, ValueError):
        return 0.0


# ----- Episodes (§7, §10) -----


def _episode_metadata(
    user_key: str | None,
    space_id: str | None,
    project_id: str | None,
    conversation_id: str | None,
    episode: Episode,
) -> dict[str, Any]:
    return {
        "user": user_key or "",
        "space": space_id or "",
        "project": project_id or "",
        "conversation_id": conversation_id or "",
        "episode_id": episode.id,
        "source_message_ids": _encode_ids(episode.source_message_ids),
        "source_message_count": len(episode.source_message_ids),
        "start_turn": int(episode.start_turn),
        "end_turn": int(episode.end_turn),
        "importance": float(episode.importance),
        "created_at": episode.created_at or "",
        "status": "active",
    }


def index_episode(
    user_key: str | None,
    space_id: str | None,
    project_id: str | None,
    episode: Episode,
    text_content: str | None = None,
) -> None:
    """Upsert one episode (its summary text + full provenance) into the index."""

    document = (text_content or episode.source_text() or "").strip()
    if not document:
        return
    collection = _get_collection(_EPISODE_COLLECTION)
    if collection is None:
        return
    try:
        collection.upsert(
            ids=[episode.id],
            documents=[document],
            metadatas=[
                _episode_metadata(
                    user_key,
                    space_id,
                    project_id,
                    episode.conversation_id,
                    episode,
                )
            ],
        )
    except Exception as exc:  # noqa: BLE001 - fail soft
        logger.warning("index_episode failed: %s", exc)


def query_episodes(
    user_key: str | None,
    project_id: str | None,
    query: str,
    *,
    k: int = 6,
    conversation_id: str = "",
    status: str = "",
) -> list[tuple[str, float]]:
    """Return ``(episode_id, similarity)`` most relevant to ``query``.

    Scoped to the project when given (episodes are project-local segments), else
    to the user. Similarity is derived from the chroma distance and squashed
    into 0..1 so it can blend with lexical/importance signals.
    """

    query = (query or "").strip()
    if not query:
        return []
    collection = _get_collection(_EPISODE_COLLECTION)
    if collection is None:
        return []
    try:
        where = _where(
            [
                ("user", user_key or ""),
                ("project", project_id or ""),
                ("conversation_id", conversation_id),
                ("status", status),
            ]
        )
        result = collection.query(
            query_texts=[query], n_results=max(1, k), where=where
        )
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        return [
            (str(episode_id), _similarity(distance))
            for episode_id, distance in zip(ids, distances)
        ]
    except Exception as exc:  # noqa: BLE001 - fail soft
        logger.warning("query_episodes failed: %s", exc)
        return []


def remove_episode(episode_id: str) -> None:
    collection = _get_collection(_EPISODE_COLLECTION)
    if collection is None:
        return
    try:
        collection.delete(ids=[episode_id])
    except Exception as exc:  # noqa: BLE001 - fail soft
        logger.warning("remove_episode failed: %s", exc)


# ----- Structured memory (§6, §11, §16) -----


def _memory_metadata(
    user_key: str | None,
    space_id: str | None,
    project_id: str | None,
    conversation_id: str | None,
    memory: StructuredMemory,
) -> dict[str, Any]:
    return {
        "user": user_key or memory.user_id or "",
        "space": space_id or "",
        "project": project_id or "",
        "conversation_id": conversation_id or memory.conversation_id or "",
        "memory_id": memory.id,
        "scope_type": memory.scope_type or "",
        "scope_id": memory.scope_id or "",
        "memory_type": memory.type or "",
        "key": memory.key or "",
        "status": memory.status or "",
        "version": int(memory.version),
        "importance": float(memory.importance),
        "confidence": float(memory.confidence),
        "source_message_ids": _encode_ids(memory.source_message_ids),
        "source_message_count": len(memory.source_message_ids),
        "created_at": memory.created_at or "",
        "updated_at": memory.updated_at or "",
    }


def index_memory(
    user_key: str | None,
    space_id: str | None,
    project_id: str | None,
    conversation_id: str | None,
    memory: StructuredMemory,
    text_content: str | None = None,
) -> None:
    """Upsert one structured memory record into the semantic index."""

    document = (text_content or f"{memory.key} = {memory.value}").strip()
    if not document or not memory.id:
        return
    collection = _get_collection(_MEMORY_COLLECTION)
    if collection is None:
        return
    try:
        collection.upsert(
            ids=[memory.id],
            documents=[document],
            metadatas=[
                _memory_metadata(
                    user_key, space_id, project_id, conversation_id, memory
                )
            ],
        )
    except Exception as exc:  # noqa: BLE001 - fail soft
        logger.warning("index_memory failed: %s", exc)


def query_memories(
    user_key: str | None,
    query: str,
    *,
    k: int = 8,
    project_id: str = "",
    conversation_id: str = "",
    scope_type: str = "",
    status: str = "",
    memory_type: str = "",
) -> list[tuple[str, float]]:
    """Return ``(memory_id, similarity)`` for a user, filtered by metadata (§16).

    Always filtered by ``user`` first, so one user's index can never leak into
    another's results even if several users share a Chroma root.
    """

    query = (query or "").strip()
    if not query:
        return []
    collection = _get_collection(_MEMORY_COLLECTION)
    if collection is None:
        return []
    try:
        where = _where(
            [
                ("user", user_key or ""),
                ("project", project_id),
                ("conversation_id", conversation_id),
                ("scope_type", scope_type),
                ("status", status),
                ("memory_type", memory_type),
            ]
        )
        result = collection.query(
            query_texts=[query], n_results=max(1, k), where=where
        )
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        return [
            (str(memory_id), _similarity(distance))
            for memory_id, distance in zip(ids, distances)
        ]
    except Exception as exc:  # noqa: BLE001 - fail soft
        logger.warning("query_memories failed: %s", exc)
        return []


def remove_memory(memory_id: str) -> None:
    collection = _get_collection(_MEMORY_COLLECTION)
    if collection is None:
        return
    try:
        collection.delete(ids=[memory_id])
    except Exception as exc:  # noqa: BLE001 - fail soft
        logger.warning("remove_memory failed: %s", exc)


# ----- Test seams -----


def disable() -> None:
    """Test seam: force the vector index off without touching disk."""

    global _disabled
    with _lock:
        _collections.clear()
        _disabled = True


def reset() -> None:
    """Test seam: clear cached state so the next call re-initialises."""

    global _disabled
    with _lock:
        _collections.clear()
        _disabled = False
