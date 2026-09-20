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

"""Environment-driven knobs for the hybrid conversational memory system.

Every tunable lives here so behaviour can be changed in the field without a
code edit, and so the *defaults* are visible in one place. All accessors are
cheap and tolerant: a malformed env value logs once and falls back rather than
raising, because the memory layer must never break a chat turn.

Design reference: ``hybrid_memory.md`` sections 4-6 (window + thresholds),
21 (ranking), 25 (context budgeting).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("memory.hybrid.config")


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %d", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default


def enabled() -> bool:
    """Master switch.

    Default OFF: the hybrid path is additive and the proven rolling-summary path
    keeps serving traffic until the hybrid retrieval is evaluated (``§40-41``).
    Flip ``UNDISCLOSED_HYBRID_MEMORY=1`` to route through it.
    """

    return _env_flag("UNDISCLOSED_HYBRID_MEMORY", False)


def token_estimate(text: str) -> int:
    """Rough token count. 1 token ~= 4 chars, matching the frontend + builder."""

    return max(1, (len(text) + 3) // 4) if text else 0


# ----- Recent context window (§4-6) -----


def recent_token_budget() -> int:
    """Token budget for the verbatim recent window (default 6,000)."""

    return max(256, _env_int("UNDISCLOSED_HYBRID_RECENT_TOKENS", 6000))


def soft_threshold() -> float:
    """Fraction of the window at which boundary-aware eviction is attempted."""

    return min(1.0, max(0.1, _env_float("UNDISCLOSED_HYBRID_SOFT_THRESHOLD", 0.8)))


def hard_threshold() -> float:
    """Fraction at/above which eviction is forced (deterministic fallback)."""

    hard = _env_float("UNDISCLOSED_HYBRID_HARD_THRESHOLD", 1.0)
    return max(soft_threshold(), hard)


# ----- Episodes (§7, §33) -----


def episode_max_turns() -> int:
    """Upper bound on messages in one episode before it is split further."""

    return max(4, _env_int("UNDISCLOSED_HYBRID_EPISODE_MAX_TURNS", 40))


def episode_summary_max_chars() -> int:
    return max(200, _env_int("UNDISCLOSED_HYBRID_EPISODE_SUMMARY_CHARS", 1200))


# ----- Retrieval (§15-22, §25) -----


def semantic_top_k() -> int:
    return max(1, _env_int("UNDISCLOSED_HYBRID_SEMANTIC_K", 6))


def lexical_top_k() -> int:
    return max(1, _env_int("UNDISCLOSED_HYBRID_LEXICAL_K", 8))


def exact_top_k() -> int:
    return max(1, _env_int("UNDISCLOSED_HYBRID_EXACT_K", 4))


def rerank_top_k() -> int:
    return max(1, _env_int("UNDISCLOSED_HYBRID_RERANK_K", 8))


def ranking_weights() -> dict[str, float]:
    """Weights for the hybrid score (§21). Configurable, defaulted sensibly."""

    return {
        "semantic": _env_float("UNDISCLOSED_HYBRID_W_SEMANTIC", 0.35),
        "lexical": _env_float("UNDISCLOSED_HYBRID_W_LEXICAL", 0.30),
        "topic": _env_float("UNDISCLOSED_HYBRID_W_TOPIC", 0.10),
        "entity": _env_float("UNDISCLOSED_HYBRID_W_ENTITY", 0.10),
        "importance": _env_float("UNDISCLOSED_HYBRID_W_IMPORTANCE", 0.05),
        "recency": _env_float("UNDISCLOSED_HYBRID_W_RECENCY", 0.10),
        # Project/entity match and memory-type match (§17). Both signals default
        # to 0.0 when a caller does not supply them, so these weights are inert
        # unless something sets them.
        "project": _env_float("UNDISCLOSED_HYBRID_W_PROJECT", 0.15),
        "type": _env_float("UNDISCLOSED_HYBRID_W_TYPE", 0.05),
    }


# ----- Context budgeting (§25) -----
#
# Section budgets as *fractions of the total* so a caller can hand us any
# overall token budget and the proportions stay sane. The builder shrinks or
# expands them per query type (§25).
def section_budget_fractions() -> dict[str, float]:
    return {
        "instructions": _env_float("UNDISCLOSED_HYBRID_B_INSTRUCTIONS", 0.06),
        "active_memory": _env_float("UNDISCLOSED_HYBRID_B_ACTIVE_MEMORY", 0.10),
        "working_memory": _env_float("UNDISCLOSED_HYBRID_B_WORKING_MEMORY", 0.08),
        "historical": _env_float("UNDISCLOSED_HYBRID_B_HISTORICAL", 0.26),
        "exact": _env_float("UNDISCLOSED_HYBRID_B_EXACT", 0.10),
        "recent": _env_float("UNDISCLOSED_HYBRID_B_RECENT", 0.40),
    }


def extraction_enabled() -> bool:
    """Whether the async run-end pipeline extracts episodes/memories."""

    return _env_flag("UNDISCLOSED_HYBRID_EXTRACTION", True)


def durable_jobs() -> bool:
    """Route post-run extraction through the durable, retryable job table (§21).

    Default ON: a lost background thread used to lose the memory for that run
    entirely; a durable job survives a restart and is retried. Set
    ``UNDISCLOSED_HYBRID_DURABLE_JOBS=0`` to fall back to the plain thread.
    """

    return _env_flag("UNDISCLOSED_HYBRID_DURABLE_JOBS", True)


def recover_jobs_on_startup() -> bool:
    """Drain durable memory jobs once at Brain start-up (§20).

    Defaults to the master hybrid switch: when the hybrid layer is on, a restart
    must not silently strand a pending extraction. Override with
    ``UNDISCLOSED_HYBRID_JOB_RECOVERY=0/1``.
    """

    return _env_flag("UNDISCLOSED_HYBRID_JOB_RECOVERY", enabled())


def background_pipeline() -> bool:
    """Run the run-end pipeline on a background thread (off the response path).

    ``on_run_end`` is synchronous; a thread keeps extraction + embedding off the
    critical path (§28) without needing an event loop.
    """

    return _env_flag("UNDISCLOSED_HYBRID_BACKGROUND", True)


# ----- Optional LLM extraction pass (§9, §12, §29-30) -----
#
# hybrid_memory.md treats extraction as a *model* job; the shipped extractor is
# deterministic by design. The model pass is opt-in and rolls out in three
# stages so it never becomes authoritative before it is evaluated.

LLM_EXTRACTION_OFF = "off"
LLM_EXTRACTION_SHADOW = "shadow"
LLM_EXTRACTION_WRITE = "write"

_LLM_OFF_TOKENS = frozenset({"off", "0", "false", "no", "none"})
_LLM_SHADOW_TOKENS = frozenset({"1", "true", "yes", "on", "shadow", "compare"})
_LLM_WRITE_TOKENS = frozenset({"write", "live", "apply", "authoritative"})


def llm_extraction_mode() -> str:
    """How the optional LLM extraction pass runs.

    - ``off`` (default): no model call at all; the deterministic planner is the
      only extractor.
    - ``shadow``: the model runs alongside the planner and the two outputs are
      logged for comparison, but only the deterministic result is written.
    - ``write``: the model authors the episode prose and proposes memory ops;
      the deterministic planner stays the fallback and every proposal still
      passes through ``HybridStore.apply_ops`` validation before it is stored.

    A bare truthy value (``1``/``true``/``yes``/``on``) maps to ``shadow`` --
    per ``research1.md`` we never make the model authoritative just by flipping a
    boolean; that needs the explicit ``write``.
    """

    raw = (os.environ.get("UNDISCLOSED_HYBRID_LLM_EXTRACTION") or "").strip().lower()
    if not raw:
        return LLM_EXTRACTION_OFF
    if raw in _LLM_OFF_TOKENS:
        return LLM_EXTRACTION_OFF
    if raw in _LLM_SHADOW_TOKENS:
        return LLM_EXTRACTION_SHADOW
    if raw in _LLM_WRITE_TOKENS:
        return LLM_EXTRACTION_WRITE
    logger.warning(
        "Invalid UNDISCLOSED_HYBRID_LLM_EXTRACTION=%r; using off", raw
    )
    return LLM_EXTRACTION_OFF


def llm_extraction_enabled() -> bool:
    """True when the model pass should run (shadow or authoritative)."""

    return llm_extraction_mode() != LLM_EXTRACTION_OFF


def llm_extraction_shadow() -> bool:
    """True when the model pass runs but must not write (evaluation only)."""

    return llm_extraction_mode() == LLM_EXTRACTION_SHADOW


def llm_extraction_max_events() -> int:
    """Cap on messages handed to one extraction call (keeps the prompt small)."""

    return max(2, _env_int("UNDISCLOSED_HYBRID_LLM_MAX_EVENTS", 40))


def llm_extraction_max_chars() -> int:
    """Per-message character cap inside the extraction prompt."""

    return max(200, _env_int("UNDISCLOSED_HYBRID_LLM_MSG_CHARS", 1500))


def llm_extraction_max_ops() -> int:
    """Ceiling on memory ops accepted from one model response."""

    return max(1, _env_int("UNDISCLOSED_HYBRID_LLM_MAX_OPS", 12))


def llm_extraction_min_events() -> int:
    """Below this many non-empty messages a slice is not worth a model call."""

    return max(2, _env_int("UNDISCLOSED_HYBRID_LLM_MIN_EVENTS", 4))


def llm_extraction_turn_ops() -> bool:
    """Also run the model on the latest turn to keep fresh decisions immediate.

    Without this, durable facts would only be model-extracted once their turns
    are evicted into an episode, which on a young conversation may be never.
    """

    return _env_flag("UNDISCLOSED_HYBRID_LLM_TURN_OPS", True)
