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

"""Semantic similarity against project descriptions (§14).

§14 lists, next to lexical matching, "semantic similarity against project
descriptions". That is the missing half of project resolution: a new thread that
says "continue the app that tracks what I eat" should find the project described
as "meal planning and nutrition tracker" even though *none* of its words appear
in the request. Lexical overlap alone cannot do that; embeddings can.

This module supplies exactly that one signal, and nothing else:

* only project **descriptions** are embedded -- project *names* are already
  handled lexically by :mod:`app.memory.hybrid.resolver`, so embedding them adds
  nothing and would only blur the two signals;
* the request is embedded once and compared to each description by cosine;
* the score is rescaled so unrelated text contributes 0 (see the cosine floor in
  :mod:`app.memory.hybrid.config`), because raw MiniLM cosine for unrelated
  sentences is never actually 0 and a naive blend would nudge every project.

Everything here is **fail-soft** (§32): a missing chromadb/onnxruntime, an
unreadable description, a slow first model load -- any of these degrade to "no
semantic signal" (an empty map), never an exception into the chat turn. When a
project has no description the signal is inert, so a tree that predates
descriptions resolves exactly as the lexical resolver always did.

The embedder is chromadb's default on-device MiniLM ONNX function -- the same
one the episode/memory index uses -- so nothing leaves the machine (local-first).
Unchanged descriptions are embedded once and cached in-process, so repeat
resolutions are cheap.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Iterable

from app.memory.hybrid.config import (
    project_semantic_cosine_floor,
    project_semantic_enabled,
    project_semantic_max_projects,
    project_semantic_min_chars,
)
from app.memory.hybrid.schema import Project

logger = logging.getLogger("memory.hybrid.project_semantic")

Embedder = Callable[[list[str]], list[list[float]]]

# How many query embeddings to remember (queries repeat within a session; this
# keeps a burst of identical resolutions from re-embedding).
_QUERY_CACHE_MAX = 64

_lock = threading.Lock()
_disabled = False
_embedder: Embedder | None = None
_embedder_override: Embedder | None = None
# project_id -> (description hash, vector)
_description_cache: dict[str, tuple[int, list[float]]] = {}
# query text -> vector
_query_cache: dict[str, list[float]] = {}


def _get_embedder() -> Embedder | None:
    """Return the description embedder, or None when it cannot be created.

    Prefers an injected embedder (tests); otherwise lazily builds chromadb's
    default on-device MiniLM function. Construction is cached and best-effort.
    """

    global _embedder
    if _embedder_override is not None:
        return _embedder_override
    if _embedder is not None:
        return _embedder
    with _lock:
        if _embedder is not None:
            return _embedder
        try:
            from chromadb.utils import embedding_functions

            _embedder = embedding_functions.DefaultEmbeddingFunction()
            logger.info("project semantic embedder ready (on-device MiniLM)")
        except Exception as exc:  # noqa: BLE001 - fail soft
            logger.warning("project semantic embedder unavailable: %s", exc)
            _embedder = None
        return _embedder


def _as_vectors(raw: Any, expected: int) -> list[list[float]]:
    """Coerce an embedder result into ``expected`` plain float lists."""

    if raw is None:
        return []
    vectors: list[list[float]] = []
    for vector in raw:
        try:
            vectors.append([float(x) for x in vector])
        except (TypeError, ValueError):
            return []
    if len(vectors) != expected:
        return []
    return vectors


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / ((na**0.5) * (nb**0.5))


def _rescale(cosine: float, floor: float) -> float:
    """Map cosine into a 0..1 signal, 0 at/below ``floor``.

    Unrelated MiniLM cosines cluster well above 0, so without this floor every
    project would receive a small positive nudge. Subtracting the floor keeps
    "unrelated" honestly at zero and spreads the useful range over 0..1.
    """

    if cosine <= floor:
        return 0.0
    span = max(1e-6, 1.0 - floor)
    return max(0.0, min(1.0, (cosine - floor) / span))


def _description_text(project: Project) -> str:
    """The text embedded for a project: its name as context + description.

    The description can be terse and omit the product name; prefixing the name
    gives the embedder a little grounding without turning this into a name match
    (names are still scored lexically by the resolver).
    """

    description = (project.description or "").strip()
    name = (project.name or "").strip()
    if name and description:
        return f"{name}\n{description}"
    return description or name


def _eligible(projects: Iterable[Project]) -> list[Project]:
    """Projects worth embedding: a substantive description, newest first, capped."""

    floor_chars = project_semantic_min_chars()
    candidates = [
        project
        for project in projects
        if (project.description or "").strip()
        and len((project.description or "").strip()) >= floor_chars
    ]
    # Deterministic order: most recently updated first, then id, then cap. This
    # bounds embedding work on an account with many projects.
    candidates.sort(key=lambda p: ((p.updated_at or ""), p.id), reverse=True)
    return candidates[: project_semantic_max_projects()]


def _query_vector(embedder: Embedder, query: str) -> list[float] | None:
    cached = _query_cache.get(query)
    if cached is not None:
        return cached
    vectors = _as_vectors(embedder([query]), 1)
    if not vectors:
        return None
    vector = vectors[0]
    with _lock:
        if len(_query_cache) >= _QUERY_CACHE_MAX:
            _query_cache.pop(next(iter(_query_cache)), None)
        _query_cache[query] = vector
    return vector


def _description_vector(
    embedder: Embedder, project: Project, text: str
) -> list[float] | None:
    key = project.id or text
    digest = hash(text)
    cached = _description_cache.get(key)
    if cached is not None and cached[0] == digest:
        return cached[1]
    vectors = _as_vectors(embedder([text]), 1)
    if not vectors:
        return None
    vector = vectors[0]
    with _lock:
        _description_cache[key] = (digest, vector)
    return vector


def semantic_scores(
    query: str,
    projects: Iterable[Project],
    *,
    embedder: Embedder | None = None,
) -> dict[str, float]:
    """Per-project semantic similarity of ``query`` to each description, 0..1.

    Returns ``{project_id: score}`` for projects whose description is
    semantically close to ``query``; projects that are unrelated (or have no
    usable description) are simply absent. An empty map means "no semantic
    signal" and callers should fall back to their lexical score. This function
    never raises.
    """

    if _disabled or not project_semantic_enabled():
        return {}
    query = (query or "").strip()
    if len(query) < 3:
        return {}
    candidates = _eligible(projects)
    if not candidates:
        return {}
    active = embedder or _get_embedder()
    if active is None:
        return {}
    try:
        query_vector = _query_vector(active, query)
        if query_vector is None:
            return {}
        floor = project_semantic_cosine_floor()
        scores: dict[str, float] = {}
        for project in candidates:
            text = _description_text(project)
            if not text:
                continue
            vector = _description_vector(active, project, text)
            if vector is None:
                continue
            score = _rescale(_cosine(query_vector, vector), floor)
            if score > 0.0:
                scores[project.id] = score
        return scores
    except Exception as exc:  # noqa: BLE001 - never break a turn
        logger.warning("project semantic scoring failed: %s", exc)
        return {}


# ----- Test seams -----


def set_embedder(embedder: Embedder | None) -> None:
    """Inject an embedder (tests) and re-enable the signal."""

    global _embedder_override, _disabled
    with _lock:
        _embedder_override = embedder
        _disabled = False
        _description_cache.clear()
        _query_cache.clear()


def disable() -> None:
    """Test seam: force the signal off without touching the model or disk."""

    global _disabled
    with _lock:
        _disabled = True


def reset() -> None:
    """Test seam: clear caches and overrides so the next call re-initialises."""

    global _disabled, _embedder_override
    with _lock:
        _disabled = False
        _embedder_override = None
        _description_cache.clear()
        _query_cache.clear()
