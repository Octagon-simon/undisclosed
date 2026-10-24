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

"""Application-controlled memory-key canonicalization (``hybrid_memory.md`` §13).

The extractor must not be able to invent equivalent keys (``database`` vs
``db`` vs ``databaseChoice``). Keys are normalised here, against a fixed alias
table, so ``UPSERT`` of the same concept updates the existing record instead of
creating a near-duplicate. This is the single place the key vocabulary lives.
"""

from __future__ import annotations

import hashlib
import re

_NON_KEY = re.compile(r"[^a-z0-9]+")

# Fixed synonym table. Deliberately small and explicit: an unknown phrase is
# normalised mechanically rather than guessed at, so we never silently merge
# two genuinely different concepts.
_ALIASES: dict[str, str] = {
    "db": "database",
    "databasechoice": "database",
    "databases": "database",
    "selecteddatabase": "database",
    "databaseused": "database",
    "datastore": "database",
    "repo": "repository",
    "gitrepo": "repository",
    "lang": "language",
    "framework": "framework",
    "timeoutvalue": "timeout",
    "retrycount": "retries",
    "retry": "retries",
    "portnumber": "port",
    "ui": "ui",
    "ux": "ui",
    "frontendframework": "frontend",
    "backendframework": "backend",
    "package manager": "package_manager",
    "packagemanager": "package_manager",
}


def _squash(text: str) -> str:
    return _NON_KEY.sub("", (text or "").lower())


def normalize_key(key: str) -> str:
    """Lowercase snake_case key with filler words removed."""

    lowered = (key or "").strip().lower()
    alias = _ALIASES.get(_squash(lowered))
    if alias:
        return alias
    # Strip a leading article/possessive that adds nothing to identity.
    lowered = re.sub(r"^(the|our|my|a|an)\s+", "", lowered)
    slug = _NON_KEY.sub("_", lowered).strip("_")
    slug = re.sub(r"_+", "_", slug)
    return slug or "unspecified"


def key_namespace(memory_type: str) -> str:
    """Namespace a key belongs to, derived from its type (§13)."""

    t = (memory_type or "").strip().lower()
    if t == "decision":
        return "technical_decision"
    if t == "preference":
        return "preference"
    if t == "constraint":
        return "constraint"
    if t == "goal":
        return "goal"
    return "fact"


def identity(memory_type: str, key: str) -> str:
    """Stable identity for dedup/supersession: ``type::normalized_key``."""

    return f"{(memory_type or '').strip().lower()}::{normalize_key(key)}"


def normalize_wording(text: str) -> str:
    """Lowercase, punctuation-free form of a value, for re-statement matching."""

    return _NON_KEY.sub(" ", (text or "").lower()).strip()


# Words that carry no identity in a rule value. Without this every prohibition
# starting "not ..." would share a prefix and collide.
_RULE_FILLER = frozenset(
    {
        "not", "never", "always", "the", "a", "an", "my", "our", "your",
        "this", "that", "these", "those", "to", "in", "on", "at", "of",
        "for", "with", "and", "or", "but", "is", "are", "be", "been",
        "do", "does", "did", "must", "should", "would", "could", "will",
        "have", "has", "had", "any", "all", "from", "into", "about",
    }
)
_RULE_KEY_WORDS = 4


def rule_key(value: str) -> str:
    """A stable, value-derived key for a standing rule.

    Two different prohibitions get different identities, so the second one can
    no longer supersede the first (the old fallback key was the literal
    ``"constraint"``). The same value always maps to the same key, which makes a
    repeat statement an idempotent merge instead of a duplicate.
    """

    text = (value or "").strip().lower()
    words = [
        word
        for word in _NON_KEY.split(text)
        if len(word) > 2 and word not in _RULE_FILLER
    ][:_RULE_KEY_WORDS]
    if words:
        return "rule_" + "_".join(words)
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"rule_{digest}"
