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

"""Hybrid ranking + reranking (§21, §23).

Blends the retrieval signals into one score so a semantically-close-but-stale
episode does not outrank an exact recent message, and vice versa. Weights come
from :mod:`app.memory.hybrid.config`, so behaviour is tunable without a code
edit. Each ranked item keeps its per-signal breakdown for observability.
"""

from __future__ import annotations

from app.memory.hybrid import text as T
from app.memory.hybrid.config import ranking_weights
from app.memory.hybrid.schema import RetrievedItem


def _entity_score(text: str, query: str) -> float:
    query_entities = T.entities(query)
    if not query_entities:
        return 0.0
    text_entities = T.entities(text)
    if not text_entities:
        return 0.0
    hits = len(query_entities & text_entities)
    return hits / len(query_entities)


def score_item(
    item: RetrievedItem,
    query: str,
    *,
    semantic: float = 0.0,
    lexical: float = 0.0,
    recency: float = 0.0,
    weights: dict[str, float] | None = None,
) -> RetrievedItem:
    """Return ``item`` annotated with per-signal scores and a blended total."""

    w = weights or ranking_weights()
    topic = T.keyword_overlap(item.text, query)
    entity = _entity_score(item.text, query)
    importance = max(0.0, min(1.0, item.scores.get("importance", 0.0)))
    if "importance" not in item.scores and item.kind != "memory":
        importance = 0.0

    breakdown = {
        "semantic": round(semantic, 4),
        "lexical": round(lexical, 4),
        "topic": round(topic, 4),
        "entity": round(entity, 4),
        "importance": round(importance, 4),
        "recency": round(recency, 4),
    }
    total = (
        w.get("semantic", 0.0) * semantic
        + w.get("lexical", 0.0) * lexical
        + w.get("topic", 0.0) * topic
        + w.get("entity", 0.0) * entity
        + w.get("importance", 0.0) * importance
        + w.get("recency", 0.0) * recency
    )
    merged = dict(item.scores)
    merged.update(breakdown)
    item.scores = merged
    item.score = round(total, 4)
    return item


def recency_score(turn: int | None, max_turn: int) -> float:
    """Linearly prefer newer turns; 1.0 for the newest, ~0 for the oldest."""

    if turn is None or max_turn <= 1:
        return 0.0
    clamped = max(1, min(turn, max_turn))
    return (clamped - 1) / (max_turn - 1)


def rerank(
    items: list[RetrievedItem],
    query: str,
    *,
    max_turn: int = 0,
    top_k: int | None = None,
) -> list[RetrievedItem]:
    """Score, sort (desc), and truncate a mixed candidate list."""

    scored = [
        score_item(
            item,
            query,
            semantic=item.scores.get("semantic", 0.0),
            lexical=item.scores.get("lexical", 0.0),
            recency=recency_score(item.turn, max_turn),
        )
        for item in items
    ]
    scored.sort(key=lambda i: i.score, reverse=True)
    if top_k is not None:
        return scored[:top_k]
    return scored
