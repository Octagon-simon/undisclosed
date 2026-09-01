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

"""Semantic (vector) memory — the fact/recall layer Eigent's local store was
missing (`LocalMemoryStore.upsert_fact` was never wired). Distilled facts are
embedded and recalled by meaning, then spliced into the agent's durable context.

Backed by chromadb (a PersistentClient under ``~/.eigent/memory/semantic``) with
its default on-device MiniLM embeddings (onnxruntime) — **fully local, nothing
leaves the machine**, matching this project's local-first stance. chromadb is
agentmemory's own backend; we call it directly because agentmemory 0.4.8's query
wrapper is incompatible with current chromadb. The public shape (`remember` /
`recall`) mirrors agentmemory so it can be swapped back later.

Everything is FAIL-SOFT: any error (missing dep, disk, chromadb) is logged and
swallowed so chat/agent runs never break because of memory.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("memory.semantic")

# chromadb collection name (must be 3-512 chars of [a-zA-Z0-9._-]).
_COLLECTION = "eigent_facts"

_lock = threading.Lock()
_collection: Any | None = None
_disabled = False


def _semantic_root() -> Path:
    return Path.home() / ".eigent" / "memory" / "semantic"


def _get_collection() -> Any | None:
    """Lazily open the on-disk chromadb collection. Returns None if unavailable."""
    global _collection, _disabled
    if _collection is not None:
        return _collection
    if _disabled:
        return None
    with _lock:
        if _collection is not None:
            return _collection
        if _disabled:
            return None
        try:
            import chromadb

            root = _semantic_root()
            root.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(root))
            _collection = client.get_or_create_collection(_COLLECTION)
            logger.info("Semantic memory ready at %s", root)
            return _collection
        except Exception as exc:  # noqa: BLE001 - fail soft
            logger.warning("Semantic memory disabled: %s", exc)
            _disabled = True
            return None


def _scope_metadata(
    user_key: str | None,
    space_id: str | None,
    project_id: str | None,
) -> dict[str, str]:
    # chromadb metadata values must be primitives; empty string for "any".
    return {
        "user": user_key or "",
        "space": space_id or "",
        "project": project_id or "",
    }


def remember(
    user_key: str | None,
    space_id: str | None,
    project_id: str | None,
    text: str,
    *,
    source: str = "run",
    extra: dict[str, Any] | None = None,
) -> None:
    """Store one distilled fact/observation, scoped by user/space/project."""
    text = (text or "").strip()
    if not text:
        return
    collection = _get_collection()
    if collection is None:
        return
    try:
        meta = _scope_metadata(user_key, space_id, project_id)
        meta["source"] = source
        meta["ts"] = str(int(time.time()))
        if extra:
            for k, v in extra.items():
                meta[str(k)] = str(v)
        # Stable id per (project, text) so identical facts dedupe on re-write.
        digest = hashlib.sha256(
            f"{project_id or ''}::{text}".encode("utf-8")
        ).hexdigest()[:24]
        collection.upsert(ids=[digest], documents=[text], metadatas=[meta])
    except Exception as exc:  # noqa: BLE001 - fail soft
        logger.warning("remember() failed: %s", exc)


def recall(
    user_key: str | None,
    space_id: str | None,
    project_id: str | None,
    query: str,
    *,
    k: int = 5,
) -> list[str]:
    """Return up to ``k`` facts most relevant to ``query`` for this project."""
    query = (query or "").strip()
    if not query:
        return []
    collection = _get_collection()
    if collection is None:
        return []
    try:
        # Scope recall to the USER, not the project: personal facts (name,
        # preferences, decisions) must surface across ALL of the user's
        # conversations/projects. Semantic similarity handles relevance, so we
        # don't over-narrow by project. (project stays in metadata for
        # future project-scoped clears/queries.)
        where: dict[str, Any] | None = (
            {"user": user_key} if user_key else None
        )
        result = collection.query(
            query_texts=[query],
            n_results=max(1, k),
            where=where,
        )
        docs = (result.get("documents") or [[]])[0]
        return [d for d in docs if isinstance(d, str) and d.strip()]
    except Exception as exc:  # noqa: BLE001 - fail soft
        logger.warning("recall() failed: %s", exc)
        return []


def count(user_key: str | None = None) -> int:
    """Number of stored facts, scoped to ``user_key`` when given (else all)."""
    collection = _get_collection()
    if collection is None:
        return 0
    try:
        if user_key:
            got = collection.get(where={"user": user_key})
            return len(got.get("ids", []) or [])
        return int(collection.count())
    except Exception as exc:  # noqa: BLE001 - fail soft
        logger.warning("count() failed: %s", exc)
        return 0


def clear(user_key: str | None = None) -> int:
    """Delete stored facts (scoped to ``user_key`` when given, else all).

    Returns the number of facts removed.
    """
    collection = _get_collection()
    if collection is None:
        return 0
    try:
        got = (
            collection.get(where={"user": user_key})
            if user_key
            else collection.get()
        )
        ids = got.get("ids", []) or []
        if ids:
            collection.delete(ids=ids)
        return len(ids)
    except Exception as exc:  # noqa: BLE001 - fail soft
        logger.warning("clear() failed: %s", exc)
        return 0
