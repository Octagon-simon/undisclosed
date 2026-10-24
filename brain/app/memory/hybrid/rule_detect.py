# ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========
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
# ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========

"""Detect a standing rule in the user's message, before the agent runs.

The run-end extractor already understands prohibitions, but it runs after the
turn, so a crash or a run that never reaches the callback loses the rule. This
module is one deterministic regex pass over the incoming message: no model, no
latency, no state. The caller writes the result through ``apply_ops`` on the
same turn, so the rule is live immediately and survives a restart.

Deliberately conservative. A false positive here becomes an always-on rule that
applies to every future turn, so a sentence must look like a policy or a
correction, not just contain the word "never".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.memory.hybrid import canonical, text as T
from app.memory.hybrid.extractor import _CONSTRAINT_RES, _clean_value
from app.memory.hybrid.schema import (
    SCOPE_CONVERSATION,
    SCOPE_GLOBAL,
    SCOPE_PROJECT,
)

# "for this email", "just this once" ... a rule that must not leak.
_ONE_TIME_RE = re.compile(
    r"\b(?:just this once|this time|one[- ]?off|for now|temporarily|"
    r"for this (?:email|draft|message|chat|thread|task|prototype|demo|test)|"
    r"in this (?:chat|thread|conversation))\b",
    re.IGNORECASE,
)

# Durable language: the user is telling the agent how to work, not describing a
# one-off. Used to choose global scope and to mark the rule hard.
_DURABLE_RE = re.compile(
    r"\b(?:always|never|from now on|going forward|every time|each time|"
    r"hard rule|under no circumstances|don'?t forget|do not forget|"
    r"remember this|remember that|as i said|i told you)\b",
    re.IGNORECASE,
)

# Explicit rule assignment: "the rule is X", "remember this: X".
_ASSIGN_RE = re.compile(
    r"\b(?:hard rule|new rule|rule is|rule:)\s*[:\-]?\s*(?P<value>[^.\n;]+)",
    re.IGNORECASE,
)
_REMEMBER_RE = re.compile(
    r"\b(?:remember (?:this|that)|don'?t forget|do not forget)\b\s*[:\-]?\s*"
    r"(?P<value>[^.\n;]+)",
    re.IGNORECASE,
)

# "always X" / "please always X" / "you should always X". Anchored at the start
# of a sentence so ordinary prose ("the build always fails") is not a rule.
_ALWAYS_RE = re.compile(
    r"^(?:please\s+)?(?:you\s+(?:should\s+|must\s+|need to\s+)?)?"
    r"(?:always|from now on|going forward|every time|each time)\s+"
    r"(?P<value>[^.\n;]+)",
    re.IGNORECASE,
)

_CATEGORY_CUES = (
    ("licensing", ("license", "licence", "copyright", "attribution", "header")),
    ("privacy", ("privacy", "personal data", "gdpr", "pii")),
    ("security", ("secret", "credential", "password", "api key", "token", "auth")),
    ("product", ("ui", "ux", "design", "copy", "product")),
    ("coding", ("code", "function", "type", "test", "lint", "refactor", "file")),
    ("workflow", ("plan", "review", "commit", "merge", "deploy", "workflow")),
)

# Words that cannot carry a rule on their own. A value with fewer than two
# content words ("not again", "not do that") is chatter, not a rule.
_WEAK_WORDS = frozenset(
    {
        "not", "never", "always", "again", "that", "this", "it", "them",
        "those", "these", "about", "with", "anything", "something",
        "nothing", "ever",
    }
)


@dataclass
class RuleCandidate:
    text: str
    original: str
    scope: str
    category: str
    severity: str
    key: str
    confidence: float


def _content_words(value: str) -> list[str]:
    words = re.findall(r"[a-z0-9][a-z0-9_./-]*", (value or "").lower())
    return [w for w in words if len(w) > 2 and w not in _WEAK_WORDS]


def _category_for(text: str) -> str:
    lowered = (text or "").lower()
    for name, cues in _CATEGORY_CUES:
        if any(cue in lowered for cue in cues):
            return name
    return "other"


def _scope_for(sentence: str) -> str:
    if _ONE_TIME_RE.search(sentence):
        return SCOPE_CONVERSATION
    if _DURABLE_RE.search(sentence):
        return SCOPE_GLOBAL
    return SCOPE_PROJECT


def _value_from(sentence: str) -> tuple[str, float] | None:
    """``(value, confidence)`` for one sentence, or None when it is not a rule."""

    match = _ASSIGN_RE.search(sentence)
    if match:
        value = _clean_value(match.group("value"))
        if value:
            return value, 0.9

    match = _REMEMBER_RE.search(sentence)
    if match:
        value = _clean_value(match.group("value"))
        if value:
            return value, 0.9

    for pattern in _CONSTRAINT_RES:
        match = pattern.search(sentence)
        if match:
            value = _clean_value(f"not {match.group('value')}")
            if value:
                return value, 0.8

    match = _ALWAYS_RE.match(sentence.strip())
    if match:
        value = _clean_value(match.group("value"))
        if value:
            return value, 0.75
    return None


def detect(text: str) -> list[RuleCandidate]:
    """Every standing rule stated in one user message (possibly none)."""

    if not (text or "").strip():
        return []

    candidates: dict[str, RuleCandidate] = {}
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        sentence = T.collapse(sentence).strip()
        if len(sentence) < 6 or sentence.endswith("?"):
            continue
        extracted = _value_from(sentence)
        if extracted is None:
            continue
        value, confidence = extracted
        if len(_content_words(value)) < 2:
            continue
        scope = _scope_for(sentence)
        severity = "soft" if scope == SCOPE_CONVERSATION else "hard"
        key = canonical.rule_key(value)
        candidate = RuleCandidate(
            text=value,
            original=T.truncate(sentence, 400),
            scope=scope,
            category=_category_for(f"{value} {sentence}"),
            severity=severity,
            key=key,
            confidence=confidence,
        )
        current = candidates.get(key)
        if current is None or candidate.confidence > current.confidence:
            candidates[key] = candidate

    return list(candidates.values())
