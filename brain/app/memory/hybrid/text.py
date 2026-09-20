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

"""Pure text utilities + a compact BM25 for lexical/raw retrieval (§17, §21).

No model calls; everything here is deterministic so it can run on the critical
path cheaply. ``tokenize`` deliberately keeps identifier-shaped tokens
(``user_id``, ``app.py``, ``https://x``, ``v1.2.3``, ``#4f2a``) intact because
exact-recall queries are precisely about those tokens (§17: commit hashes,
filenames, ports, URLs).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable

# A token is a run of identifier-ish characters. This preserves dots, slashes,
# colons, hashes and dashes so "app.py", "8080", "sha256:ab12", "api/v2" and
# "v1.2.3" survive intact instead of being shredded into stopword noise.
_TOKEN_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./:@#\-]*")

_SENTENCE_CUTS = (". ", "! ", "? ", "\n", "; ")

_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "if", "then", "of", "to", "in",
        "on", "at", "by", "for", "with", "as", "is", "are", "was", "were",
        "be", "been", "being", "it", "its", "this", "that", "these", "those",
        "i", "you", "we", "they", "he", "she", "them", "us", "me", "my",
        "our", "your", "their", "so", "do", "does", "did", "can", "will",
        "would", "should", "could", "have", "has", "had", "not", "no", "yes",
        "just", "about", "into", "from", "up", "down", "out", "over", "again",
        # contraction fragments produced by splitting "we'll" / "don't"
        "ll", "re", "ve", "d",
    }
)

# Trailing punctuation to strip from a token (sentence periods, list colons).
_TOKEN_TRAILING = "./:@#-,"


def collapse(text: str) -> str:
    """Collapse all whitespace runs to single spaces and strip the edges."""

    return " ".join((text or "").split())


def truncate(text: str, max_chars: int, ellipsis: str = "...") -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    keep = max(0, max_chars - len(ellipsis))
    return text[:keep] + ellipsis


def tokenize(text: str, *, drop_stopwords: bool = True) -> list[str]:
    """Lowercased identifier-aware tokens; stopwords optional."""

    tokens = [
        cleaned
        for raw in _TOKEN_RE.findall(text or "")
        if (cleaned := raw.lower().rstrip(_TOKEN_TRAILING))
    ]
    if drop_stopwords:
        tokens = [t for t in tokens if t not in _STOPWORDS]
    return tokens


def terms(text: str) -> set[str]:
    return set(tokenize(text))


def tokenize_len(text: str) -> int:
    """Number of content tokens; used as a cheap token proxy for budgeting."""

    return len(tokenize(text))


def sentences(text: str, *, max_sentences: int | None = None) -> list[str]:
    """Split on sentence-ish boundaries, preserving order, dropping empties."""

    raw = collapse(text)
    if not raw:
        return []
    parts: list[str] = [raw]
    for cut in _SENTENCE_CUTS:
        next_parts: list[str] = []
        for part in parts:
            next_parts.extend(part.split(cut))
        parts = next_parts
    out = [p.strip() for p in parts if p.strip()]
    if max_sentences is not None:
        out = out[:max_sentences]
    return out


# Matches the "exact detail" shapes the spec calls out (numbers, hashes, URLs,
# filenames, ports, versions). Used by the router + ranking entity signal.
_ENTITY_RES = (
    re.compile(r"https?://[^\s,;)\]]+"),
    re.compile(r"[\w./-]+\.[A-Za-z0-9]{1,8}\b"),  # filenames / domains
    re.compile(r"#?[0-9a-f]{7,40}\b", re.IGNORECASE),  # commit-ish hashes
    re.compile(r"\bv?\d+\.\d+(\.\d+)?\b"),  # versions
    re.compile(r"\b\d+(\.\d+)?\s?(ms|s|sec|seconds|mb|kb|gb|px|%)\b"),
    re.compile(r"\bport\s*\d+\b", re.IGNORECASE),
    re.compile(r"\b\d{2,}\b"),  # bare numbers / ports / ids
)


def entities(text: str) -> set[str]:
    """Extract exact-detail tokens (URLs, filenames, hashes, numbers...)."""

    found: set[str] = set()
    for pattern in _ENTITY_RES:
        # group(0) keeps the WHOLE match; findall would return inner groups.
        for match in pattern.finditer(text or ""):
            token = match.group(0).strip().lower()
            if token:
                found.add(token)
    return found


def _bm25(
    docs: list[list[str]],
    query_tokens: list[str],
    *,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[float]:
    """Okapi BM25 scores for every doc, in input order."""

    n = len(docs)
    if n == 0 or not query_tokens:
        return [0.0] * n
    doc_len = [len(d) for d in docs]
    avgdl = (sum(doc_len) / n) or 1.0
    df: Counter[str] = Counter()
    for d in docs:
        for term in set(d):
            df[term] += 1
    scores: list[float] = []
    for d, length in zip(docs, doc_len):
        tf = Counter(d)
        score = 0.0
        for term in query_tokens:
            if term not in tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            denom = tf[term] + k1 * (1 - b + b * (length / avgdl))
            score += idf * (tf[term] * (k1 + 1)) / (denom or 1.0)
        scores.append(score)
    return scores


def bm25_scores(
    documents: Iterable[str], query: str
) -> list[float]:
    """BM25 score every document against ``query`` (order preserved)."""

    query_tokens = tokenize(query)
    docs = [tokenize(doc) for doc in documents]
    return _bm25(docs, query_tokens)


def bm25_normalized(documents: Iterable[str], query: str) -> list[float]:
    """BM25 scores squashed to 0..1 by the max, for hybrid blending."""

    scores = bm25_scores(documents, query)
    peak = max(scores) if scores else 0.0
    if peak <= 0:
        return [0.0 for _ in scores]
    return [s / peak for s in scores]


def keyword_overlap(a: str, b: str) -> float:
    """Jaccard-ish overlap of content terms, 0..1. Used for topic/boundary."""

    ta, tb = terms(a), terms(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / max(1, min(len(ta), len(tb)))


def contains_exact(haystack: str, needle: str) -> bool:
    """Case-insensitive literal containment, whitespace-normalised."""

    needle_norm = collapse(needle).lower()
    if not needle_norm:
        return False
    return needle_norm in collapse(haystack).lower()
