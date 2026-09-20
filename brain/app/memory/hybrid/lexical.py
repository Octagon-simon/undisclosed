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

"""Lexical / exact retrieval against the authoritative raw messages (§17).

Two modes, both deterministic and model-free:

- :func:`search` — BM25 ranking over raw messages, for "where did we discuss X".
- :func:`exact_matches` — term-coverage matching that prefers messages holding
  the *exact* detail (a number, hash, filename, URL) the user asked about.

Both return ``(message_index, score, content)`` tuples where ``message_index`` is
the 1-based position in the transcript, so results can link back to the source
message (§23).
"""

from __future__ import annotations

from app.memory.events import ConversationEvent
from app.memory.hybrid import text as T

# Query tokens that carry no retrieval signal for exact-detail questions.
_EXACT_FILLER = frozenset(
    {
        "exact", "exactly", "value", "values", "number", "numbers", "what",
        "which", "did", "do", "does", "we", "i", "you", "settle", "settled",
        "on", "give", "gave", "tell", "me", "again", "please", "the", "a",
        "an", "is", "was", "were", "are", "use", "used", "using", "final",
        "finally", "eventually", "end", "up",
    }
)


def index_messages(
    events: list[ConversationEvent],
) -> list[tuple[int, ConversationEvent]]:
    """Pair each event with its 1-based transcript position (skip empties)."""

    out: list[tuple[int, ConversationEvent]] = []
    for i, event in enumerate(events, start=1):
        if (event.content or "").strip():
            out.append((i, event))
    return out


def search(
    events: list[ConversationEvent], query: str, *, k: int = 8
) -> list[tuple[int, float, ConversationEvent]]:
    """BM25 search over raw messages. Returns ``(index, normalised_score, evt)``."""

    indexed = index_messages(events)
    if not indexed or not (query or "").strip():
        return []
    documents = [event.content for _idx, event in indexed]
    scores = T.bm25_normalized(documents, query)
    ranked = sorted(
        zip(indexed, scores), key=lambda pair: pair[1], reverse=True
    )
    out: list[tuple[int, float, ConversationEvent]] = []
    for (index, event), score in ranked:
        if score <= 0:
            continue
        out.append((index, score, event))
        if len(out) >= k:
            break
    return out


def exact_matches(
    events: list[ConversationEvent], query: str, *, k: int = 4
) -> list[tuple[int, float, ConversationEvent]]:
    """Messages that contain the query's informational terms verbatim.

    Score = fraction of informational query terms present as whole tokens, with
    a bump when the message also carries an exact-detail entity (number, hash,
    URL, filename). Messages that miss every informational term are dropped, so
    this never fabricates a match from stopwords alone.
    """

    indexed = index_messages(events)
    if not indexed:
        return []
    query_terms = [
        t
        for t in T.tokenize(query or "")
        if t not in _EXACT_FILLER and len(t) > 1
    ]
    if not query_terms:
        # Query was pure filler ("what did we use?") -> fall back to entities.
        query_terms = list(T.entities(query or ""))
    if not query_terms:
        return []

    scored: list[tuple[int, float, ConversationEvent]] = []
    for index, event in indexed:
        message_terms = set(T.tokenize(event.content))
        matched = sum(1 for term in query_terms if term in message_terms)
        if matched == 0:
            continue
        coverage = matched / len(query_terms)
        # A message that actually carries an exact-detail entity (number, hash,
        # URL, filename) is what an exact-recall question wants, so it must beat
        # a message that merely repeats the topic word. Weight coverage below
        # 1.0 so the entity signal is the tie-breaker, not a rounding artifact.
        entity_hit = any(
            entity in event.content.lower() for entity in T.entities(event.content)
        )
        score = min(1.0, 0.7 * coverage + (0.3 if entity_hit else 0.0))
        scored.append((index, score, event))

    scored.sort(key=lambda row: row[1], reverse=True)
    return scored[:k]
