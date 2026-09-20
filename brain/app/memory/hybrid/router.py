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

"""Deterministic retrieval routing (§18, §22, §38).

No query-analysis LLM on the critical path. A small, explainable keyword check
decides which retrieval lanes to run and at which escalation level. Every plan
carries ``reasons`` so the observability log can answer "why did retrieval run
(or not)" without guessing (§43).
"""

from __future__ import annotations

from app.memory.hybrid import text as T
from app.memory.hybrid.schema import (
    LEVEL_BROAD,
    LEVEL_EPISODES,
    LEVEL_EXACT,
    LEVEL_MEMORY,
    LEVEL_RECENT,
    RetrievalPlan,
)

# §18 signal vocabularies.
_HISTORICAL = (
    "earlier", "previously", "last week", "last time", "back when",
    "what did we decide", "what did we say", "what did i say", "we decided",
    "we agreed", "we discussed", "remind me", "previous", "before",
    "originally", "used to", "at the start", "in the beginning", "history",
)
_EXACT = (
    "exact", "exact number", "exact value", "exact command", "exact commit",
    "exact hash", "what port", "which port", "what filename", "what file",
    "what url", "which url", "which commit", "what value", "what number",
    "how many", "what version", "what path",
)
_CURRENT_STATE = (
    "current", "right now", "now", "are we using", "are we going",
    "what database", "what framework", "what language", "what timeout",
    "which one", "what did we settle", "what are we using", "selected",
)
_CONTINUATION = (
    "continue", "go on", "keep going", "do that", "do it", "same thing",
    "change it", "the first option", "the second option", "and then",
    "next", "carry on", "proceed",
    # Multi-word pointers back, as used in the spec's own examples (§28, §36:
    # "Continue that work."). Kept explicit so a request that *names* a project
    # ("continue the Mac app", §12) is NOT swallowed as a bare continuation.
    "continue that work", "continue the work", "continue this", "continue that",
    "continue the same", "carry on with that", "keep working on that",
    "the previous one", "same as before", "change this", "do the same",
)


def _has_any(query: str, phrases: tuple[str, ...]) -> str | None:
    q = (query or "").lower()
    for phrase in phrases:
        if phrase in q:
            return phrase
    return None


def is_exact_query(query: str) -> bool:
    return _has_any(query, _EXACT) is not None


def is_historical_query(query: str) -> bool:
    return _has_any(query, _HISTORICAL) is not None


def is_continuation(query: str) -> bool:
    q = T.collapse(query or "").lower()
    if not q:
        return True
    # Trailing sentence punctuation must not stop "Continue that work." matching.
    if q.rstrip(" .!?,;") in _CONTINUATION:
        return True
    # A very short utterance with no content term is a continuation/pronoun turn.
    return len(T.tokenize(q)) == 0


def route(query: str, *, has_recent: bool = True) -> RetrievalPlan:
    """Choose lanes + escalation level for ``query``."""

    q = (query or "").strip()
    if is_continuation(q):
        return RetrievalPlan(
            level=LEVEL_RECENT,
            use_recent=True,
            reasons=["continuation: recent + working memory only"],
        )

    reasons: list[str] = []
    exact = _has_any(q, _EXACT)
    historical = _has_any(q, _HISTORICAL)
    current_state = _has_any(q, _CURRENT_STATE)

    if exact:
        reasons.append(f"exact-detail signal {exact!r}")
        return RetrievalPlan(
            level=LEVEL_EXACT,
            use_recent=True,
            use_memory=True,
            use_semantic=True,
            use_lexical=True,
            use_exact=True,
            reasons=reasons,
        )

    if historical:
        reasons.append(f"historical signal {historical!r}")
        return RetrievalPlan(
            level=LEVEL_EPISODES,
            use_recent=True,
            use_memory=True,
            use_semantic=True,
            use_lexical=True,
            reasons=reasons,
        )

    if current_state:
        reasons.append(f"current-state signal {current_state!r}")
        return RetrievalPlan(
            level=LEVEL_MEMORY,
            use_recent=True,
            use_memory=True,
            use_semantic=True,
            reasons=reasons,
        )

    # Default: light structured lookup, plus semantic only when the query has
    # real content terms to search with.
    has_terms = bool(T.tokenize(q))
    reasons.append("default: light retrieval")
    return RetrievalPlan(
        level=LEVEL_MEMORY,
        use_recent=True,
        use_memory=True,
        use_semantic=has_terms,
        reasons=reasons,
    )


def escalate(plan: RetrievalPlan, *, found: bool) -> RetrievalPlan:
    """Broaden to level 5 when a targeted level returned nothing usable (§22)."""

    if found or plan.level >= LEVEL_BROAD:
        return plan
    return RetrievalPlan(
        level=LEVEL_BROAD,
        use_recent=True,
        use_memory=True,
        use_semantic=True,
        use_lexical=True,
        use_exact=True,
        reasons=[*plan.reasons, "escalated: first pass found no evidence"],
    )
