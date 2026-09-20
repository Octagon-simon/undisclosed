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

"""Semantic (vector) index for EPISODES (§16), backed by the local chromadb.

Separate collection from ``semantic_store`` (which indexes distilled facts):
episodes are longer, self-contained segments, and mixing them with facts would
pollute both. Same on-device MiniLM embeddings, same local-only stance, same
fail-soft contract: any error logs and returns empty rather than breaking a
turn.

The public shape mirrors :mod:`app.memory.semantic_store` so the two vector
layers are symmetric and swappable.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("memory.hybrid.vector")

_COLLECTION = "eigent_episodes"

_lock = threading.Lock()
_collection: Any | None = None
_disabled = False


def _root() -> Path:
    return Path.home() / ".undisclosed" / "memory" / "semantic"


def _get_collection() -> Any | None:
    """Lazily open the on-disk episode collection. None when unavailable."""

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

            root = _root()
            root.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(root))
            _collection = client.get_or_create_collection(_COLLECTION)
            logger.info("Episode memory ready at %s", root)
            return _collection
        except Exception as exc:  # noqa: BLE001 - fail soft
            logger.warning("Episode memory disabled: %s", exc)
            _disabled = True
            return None


def _metadata(
    user_key: str | None,
    space_id: str | None,
    project_id: str | None,
    episode_id: str,
) -> dict[str, str]:
    return {
        "user": user_key or "",
        "space": space_id or "",
        "project": project_id or "",
        "episode_id": episode_id,
    }


def index_episode(
    user_key: str | None,
    space_id: str | None,
    project_id: str | None,
    episode_id: str,
    text_content: str,
) -> None:
    """Upsert one episode's text into the vector index."""

    text_content = (text_content or "").strip()
    if not text_content:
        return
    collection = _get_collection()
    if collection is None:
        return
    try:
        collection.upsert(
            ids=[episode_id],
            documents=[text_content],
            metadatas=[_metadata(user_key, space_id, project_id, episode_id)],
        )
    except Exception as exc:  # noqa: BLE001 - fail soft
        logger.warning("index_episode failed: %s", exc)


def query_episodes(
    user_key: str | None,
    project_id: str | None,
    query: str,
    *,
    k: int = 6,
) -> list[tuple[str, float]]:
    """Return ``(episode_id, similarity)`` most relevant to ``query``.

    Scoped to the project when given (episodes are project-local segments), else
    to the user. Similarity is derived from the chromadb distance and squashed
    into 0..1 so it can blend with lexical/importance signals.
    """

    query = (query or "").strip()
    if not query:
        return []
    collection = _get_collection()
    if collection is None:
        return []
    try:
        where: dict[str, Any] | None = None
        if project_id:
            where = {"project": project_id}
        elif user_key:
            where = {"user": user_key}
        result = collection.query(
            query_texts=[query], n_results=max(1, k), where=where
        )
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        out: list[tuple[str, float]] = []
        for episode_id, distance in zip(ids, distances):
            try:
                similarity = 1.0 / (1.0 + float(distance))
            except (TypeError, ValueError):
                similarity = 0.0
            out.append((str(episode_id), similarity))
        return out
    except Exception as exc:  # noqa: BLE001 - fail soft
        logger.warning("query_episodes failed: %s", exc)
        return []


def remove_episode(episode_id: str) -> None:
    collection = _get_collection()
    if collection is None:
        return
    try:
        collection.delete(ids=[episode_id])
    except Exception as exc:  # noqa: BLE001 - fail soft
        logger.warning("remove_episode failed: %s", exc)


def disable() -> None:
    """Test seam: force the vector index off without touching disk."""

    global _collection, _disabled
    with _lock:
        _collection = None
        _disabled = True


def reset() -> None:
    """Test seam: clear cached state so the next call re-initialises."""

    global _collection, _disabled
    with _lock:
        _collection = None
        _disabled = False
