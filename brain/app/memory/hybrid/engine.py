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

"""Hybrid memory engine: parallel retrieval + the end-of-run pipeline.

This is the top of the hybrid stack. Two entry points:

- :func:`retrieve` runs the cheap router, then dispatches semantic / lexical /
  exact / structured retrieval *concurrently* before generation (§15, §19), and
  reranks the union. It returns a :class:`RetrievalResult` (structured, for
  tests + observability) alongside the recent window.
- :func:`build_context` renders that result via the assembler for prompt
  injection.
- :func:`process_run_end` runs the async memory pipeline (§28): boundary-aware
  eviction into episodes, memory-op extraction, working-memory update, then
  persist + embed. It is idempotent per coverage watermark and best-effort.

Nothing here raises into the caller: a memory failure degrades context, never
the chat turn.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from app.memory.events import ConversationEvent
from app.memory.hybrid import (
    assembler,
    extractor,
    lexical,
    llm_extract,
    ranking,
    router,
    vector,
)
from app.memory.hybrid import scope as scope_mod
from app.memory.hybrid import text as T
from app.memory.hybrid.config import (
    LLM_EXTRACTION_OFF,
    LLM_EXTRACTION_WRITE,
    background_pipeline,
    exact_top_k,
    extraction_enabled,
    lexical_top_k,
    llm_extraction_mode,
    llm_extraction_turn_ops,
    recent_token_budget,
    rerank_top_k,
    semantic_top_k,
    soft_threshold,
    hard_threshold,
    token_estimate,
)
from app.memory.hybrid.schema import (
    LEVEL_RECENT,
    SCOPE_CONVERSATION,
    SCOPE_GLOBAL,
    SCOPE_PROJECT,
    Episode,
    EpisodeDraft,
    ExtractionResult,
    MemoryOp,
    RetrievalResult,
    RetrievedItem,
    StructuredMemory,
)
from app.memory.hybrid.scope import GlobalMemoryStore
from app.memory.hybrid.storage import HybridStore

logger = logging.getLogger("memory.hybrid.engine")

_MAX_EVENTS = 2000

# Upper bound on records pulled in from outside the current thread (§12, §27).
# Cross-session retrieval widens the candidate set; it must never become a dump,
# so ranking + the token budget trim from here rather than the other way round.
_MAX_CROSS_SESSION_MEMORIES = 100


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


# ----- Event loading -----


def load_events(
    store: Any, user_key: str, space_id: str, project_id: str, *, limit: int = _MAX_EVENTS
) -> list[ConversationEvent]:
    try:
        return store.read_conversation_tail(
            user_key, space_id, project_id, limit=limit
        )
    except Exception:  # noqa: BLE001 - best-effort
        logger.debug("hybrid: conversation read failed", exc_info=True)
        return []


def _recent_window(
    events: list[ConversationEvent], budget_tokens: int
) -> list[ConversationEvent]:
    """Newest messages that fit the recent token budget, oldest-first."""

    kept: list[ConversationEvent] = []
    used = 0
    for event in reversed(events):
        cost = token_estimate(event.content)
        if kept and used + cost > budget_tokens:
            break
        kept.append(event)
        used += cost
    kept.reverse()
    return kept


# ----- Structured-memory lookup (§15) -----


def _memory_item(memory: StructuredMemory) -> RetrievedItem:
    item = RetrievedItem(
        kind="memory",
        id=memory.id,
        text=f"{memory.key} = {memory.value}",
        source_message_ids=list(memory.source_message_ids),
        status=memory.status,
        scores={"importance": memory.confidence},
    )
    # Tag reach + origin so the context builder can present a cross-session hit
    # as evidence from another thread rather than current state (§12, §18).
    item.scope = memory.scope_type or SCOPE_PROJECT
    if item.scope == SCOPE_PROJECT:
        item.origin_project_id = memory.scope_id or memory.conversation_id
    elif item.scope == SCOPE_CONVERSATION:
        item.origin_project_id = memory.conversation_id
    return item


def _cross_session_memories(
    hybrid_store: HybridStore,
    *,
    user_key: str,
    space_id: str,
    project_id: str,
) -> list[StructuredMemory]:
    """Active memory from outside the current thread (§11, §12).

    Two sources, both best-effort:

    * ``global`` memory, read from the user root through
      :class:`~app.memory.hybrid.scope.GlobalMemoryStore`;
    * the user's *other* projects, so a decision made in one thread is
      discoverable from a new one.

    Capped so a long history cannot be pulled wholesale into one prompt. Any read
    error yields ``[]`` -- retrieval degrades to the current project.
    """

    out: list[StructuredMemory] = []
    try:
        global_store = GlobalMemoryStore(hybrid_store.base)
        out.extend(
            global_store.read_active_memories(user_key, space_id, project_id)
        )
    except Exception:  # noqa: BLE001 - best-effort
        logger.debug("hybrid: global memory read failed", exc_info=True)

    try:
        for other_space, other_project in scope_mod.iter_user_projects(
            hybrid_store, user_key
        ):
            if other_space == space_id and other_project == project_id:
                continue
            try:
                out.extend(
                    hybrid_store.read_active_memories(
                        user_key, other_space, other_project
                    )
                )
            except Exception:  # noqa: BLE001 - skip one unreadable project
                continue
    except Exception:  # noqa: BLE001 - best-effort
        logger.debug("hybrid: cross-project memory read failed", exc_info=True)

    by_id: dict[str, StructuredMemory] = {}
    for memory in out:
        current = by_id.get(memory.id)
        if current is None or memory.updated_at >= current.updated_at:
            by_id[memory.id] = memory
    return list(by_id.values())[:_MAX_CROSS_SESSION_MEMORIES]


def _lookup_memories(
    active: list[StructuredMemory],
    superseded: list[StructuredMemory],
    query: str,
) -> tuple[list[RetrievedItem], list[RetrievedItem]]:
    """Match memories whose key or value shares a term/entity with the query.

    Returns ``(active_hits, superseded_context)`` where superseded context is
    the history of any key currently being asked about, so the model can
    distinguish "was X" from "is X" (§11, §36).
    """

    query_terms = T.terms(query)
    query_entities = T.entities(query)
    if not query_terms and not query_entities:
        return [], []

    active_hits: list[RetrievedItem] = []
    matched_keys: set[str] = set()
    for memory in active:
        haystack = f"{memory.key} {memory.value}"
        hits = query_terms & T.terms(haystack)
        if hits or query_entities & T.entities(haystack):
            active_hits.append(_memory_item(memory))
            matched_keys.add(memory.key)

    superseded_hits: list[RetrievedItem] = []
    if matched_keys:
        for memory in superseded:
            if memory.key in matched_keys:
                superseded_hits.append(_memory_item(memory))
    return active_hits, superseded_hits


# ----- Retrieval -----


def _episode_item(episode: Episode, similarity: float = 0.0) -> RetrievedItem:
    return RetrievedItem(
        kind="episode",
        id=episode.id,
        text=(
            f"Episode \"{episode.title}\" (turns {episode.start_turn}-"
            f"{episode.end_turn}):\n{episode.summary}"
        ),
        source_message_ids=list(episode.source_message_ids),
        turn=episode.end_turn,
        scores={"semantic": similarity, "importance": episode.importance},
    )


def _message_item(
    turn: int, event: ConversationEvent, score: float
) -> RetrievedItem:
    return RetrievedItem(
        kind="message",
        id=event.event_id or f"turn_{turn}",
        text=f"Turn {turn} ({event.role}): {T.truncate(T.collapse(event.content), 600)}",
        source_message_ids=[event.event_id] if event.event_id else [],
        turn=turn,
        scores={"lexical": score},
    )


def retrieve(
    hybrid_store: HybridStore,
    *,
    user_key: str,
    space_id: str,
    project_id: str,
    conversation_id: str,
    query: str,
    token_budget: int,
    events: list[ConversationEvent] | None = None,
) -> tuple[RetrievalResult, list[ConversationEvent]]:
    """Route + run retrieval lanes concurrently + rerank (§15-22)."""

    started = time.perf_counter()
    events = events if events is not None else load_events(
        hybrid_store.base, user_key, space_id, project_id
    )
    stored = hybrid_store.base
    plan = router.route(query, has_recent=bool(events))

    recent_events = _recent_window(events, recent_token_budget())
    max_turn = len(events)

    result = RetrievalResult(
        plan=plan,
        working_memory=hybrid_store.read_working_memory(
            user_key, space_id, project_id
        ),
    )

    episode_items: list[RetrievedItem] = []
    message_items: list[RetrievedItem] = []

    def _semantic() -> list[RetrievedItem]:
        if not plan.use_semantic:
            return []
        hits = vector.query_episodes(
            user_key, project_id, query, k=semantic_top_k()
        )
        if not hits:
            return []
        episodes = {
            e.id: e
            for e in hybrid_store.read_episodes(user_key, space_id, project_id)
        }
        items: list[RetrievedItem] = []
        for episode_id, similarity in hits:
            episode = episodes.get(episode_id)
            if episode is not None:
                items.append(_episode_item(episode, similarity))
        return items

    def _lexical() -> list[RetrievedItem]:
        items: list[RetrievedItem] = []
        if plan.use_lexical:
            items.extend(
                _message_item(turn, event, score)
                for turn, score, event in lexical.search(
                    events, query, k=lexical_top_k()
                )
            )
        if plan.use_exact:
            items.extend(
                _message_item(turn, event, score)
                for turn, score, event in lexical.exact_matches(
                    events, query, k=exact_top_k()
                )
            )
        return items

    def _structured() -> tuple[list[RetrievedItem], list[RetrievedItem]]:
        if not plan.use_memory:
            return [], []
        active = hybrid_store.read_active_memories(user_key, space_id, project_id)
        # Widen to the user's other sessions only when the request actually calls
        # for history (§12). A continuation ("continue", "that") stays inside the
        # thread: pulling unrelated global/project memory into it is exactly the
        # irrelevant-recall failure §36 warns about.
        if plan.level != LEVEL_RECENT:
            seen = {m.id for m in active}
            for memory in _cross_session_memories(
                hybrid_store,
                user_key=user_key,
                space_id=space_id,
                project_id=project_id,
            ):
                if memory.id not in seen:
                    seen.add(memory.id)
                    active.append(memory)
        superseded = hybrid_store.read_memories(
            user_key, space_id, project_id, status="superseded"
        )
        return _lookup_memories(active, superseded, query)

    if plan.level == LEVEL_RECENT:
        # Continuation: no history search, but working memory still loads (done
        # above). This is the §38 "remain dormant" path.
        active_hits, superseded_hits = _structured()
    else:
        with ThreadPoolExecutor(max_workers=3) as pool:
            semantic_future = pool.submit(_semantic)
            lexical_future = pool.submit(_lexical)
            structured_future = pool.submit(_structured)
            episode_items = semantic_future.result()
            message_items = lexical_future.result()
            active_hits, superseded_hits = structured_future.result()

    result.episodes = ranking.rerank(
        episode_items, query, max_turn=max_turn, top_k=rerank_top_k()
    )
    # Dedupe messages by id keeping the highest score.
    by_id: dict[str, RetrievedItem] = {}
    for item in message_items:
        current = by_id.get(item.id)
        if current is None or item.score > current.score:
            by_id[item.id] = item
    result.messages = ranking.rerank(
        list(by_id.values()), query, max_turn=max_turn, top_k=rerank_top_k()
    )
    result.active_memories = [ranking.score_item(m, query) for m in active_hits]
    result.superseded_memories = [
        ranking.score_item(m, query) for m in superseded_hits
    ]

    result.evidence_found = _classify_evidence(result)
    result.diagnostics = {
        "conversation_id": conversation_id,
        "query": T.truncate(query, 200),
        "level": plan.level,
        "reasons": plan.reasons,
        "episodes": [e.id for e in result.episodes],
        "messages": [m.id for m in result.messages],
        "memories": [m.id for m in result.active_memories],
        "cross_session_memories": [
            m.id
            for m in result.active_memories
            if m.scope == SCOPE_GLOBAL
            or (m.origin_project_id and m.origin_project_id != project_id)
        ],
        "scores": {
            "episodes": [e.score for e in result.episodes],
            "messages": [m.score for m in result.messages],
        },
        "evidence_found": result.evidence_found,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    _log_retrieval(hybrid_store, user_key, space_id, project_id, result)
    return result, recent_events


def _classify_evidence(result: RetrievalResult) -> str:
    exact_hit = any(
        m.scores.get("lexical", 0.0) >= 0.5 for m in result.messages
    ) and result.plan.use_exact
    if exact_hit:
        return "exact"
    if result.episodes or result.messages or result.active_memories:
        return "approximate"
    return "none"


def _log_retrieval(
    hybrid_store: HybridStore,
    user_key: str,
    space_id: str,
    project_id: str,
    result: RetrievalResult,
) -> None:
    payload = dict(result.diagnostics)
    payload["ts"] = _utc_now()
    hybrid_store.append_retrieval_log(user_key, space_id, project_id, payload)


def build_context(
    hybrid_store: HybridStore,
    *,
    user_key: str,
    space_id: str,
    project_id: str,
    conversation_id: str,
    query: str,
    token_budget: int,
    events: list[ConversationEvent] | None = None,
) -> str:
    """Retrieve + assemble the tagged context block. Empty string when nothing."""

    result, recent_events = retrieve(
        hybrid_store,
        user_key=user_key,
        space_id=space_id,
        project_id=project_id,
        conversation_id=conversation_id,
        query=query,
        token_budget=token_budget,
        events=events,
    )
    rendered = assembler.assemble(
        result, recent_events=recent_events, token_budget=token_budget
    )
    result.diagnostics["final_token_estimate"] = token_estimate(rendered)
    return rendered


# ----- Optional LLM extraction pass (§9, §12, §29-30; research1.md) -----


def _known_message_ids(events: list[ConversationEvent]) -> set[str]:
    """Every message id that actually exists in this conversation."""

    return {e.event_id for e in events if e.event_id}


def _slice_pairs(
    events: list[ConversationEvent], start_turn: int, end_turn: int
) -> list[tuple[int, ConversationEvent]]:
    """``(turn, event)`` for the non-empty messages in ``[start_turn, end_turn]``."""

    return [
        (turn, event)
        for turn, event in enumerate(events, start=1)
        if start_turn <= turn <= end_turn and (event.content or "").strip()
    ]


def _merge_draft(episode: Episode, draft: EpisodeDraft) -> Episode:
    """Overlay a model draft onto the planner's episode boundaries.

    The id, turn range and source links always come from the deterministic plan;
    only the prose and importance can come from the model. A bad draft can
    therefore never change which messages an episode covers or claims to be
    backed by (§30), which is what makes "model writes the prose, planner owns
    the structure" enforceable rather than aspirational.
    """

    return Episode(
        id=episode.id,
        conversation_id=episode.conversation_id,
        start_turn=episode.start_turn,
        end_turn=episode.end_turn,
        title=(draft.title.strip() or episode.title),
        summary=(draft.summary.strip() or episode.summary),
        source_message_ids=list(episode.source_message_ids),
        topic=(draft.topic.strip() or episode.topic),
        importance=(draft.importance or episode.importance),
        created_at=episode.created_at,
        schema_version=episode.schema_version,
    )


def _log_extraction(
    hybrid_store: HybridStore,
    *,
    mode: str,
    phase: str,
    user_key: str,
    space_id: str,
    project_id: str,
    conversation_id: str,
    now: str,
    start_turn: int,
    end_turn: int,
    source_message_ids: list[str],
    deterministic_episode: Episode | None,
    deterministic_ops: list[MemoryOp],
    result: ExtractionResult | None,
) -> None:
    """Append one model-vs-deterministic comparison row.

    This is the evaluation surface. In shadow mode it is the only output of the
    model path, which is deliberate: ``research1.md`` wants episode quality,
    memory precision, false memories, missed decisions and incorrect supersedes
    inspected before the model is allowed to mutate production memory.
    """

    hybrid_store.append_extraction_log(
        user_key,
        space_id,
        project_id,
        {
            "ts": now,
            "mode": mode,
            "phase": phase,
            "conversation_id": conversation_id,
            "start_turn": start_turn,
            "end_turn": end_turn,
            "source_message_ids": source_message_ids,
            "deterministic": {
                "episode": (
                    deterministic_episode.to_dict()
                    if deterministic_episode is not None
                    else None
                ),
                "ops": [op.to_dict() for op in deterministic_ops],
            },
            "llm": result.to_dict() if result is not None else None,
        },
    )


def _llm_episode_pass(
    hybrid_store: HybridStore,
    episodes: list[Episode],
    events: list[ConversationEvent],
    *,
    mode: str,
    user_key: str,
    space_id: str,
    project_id: str,
    conversation_id: str,
    active_memories: list[StructuredMemory],
    now: str,
) -> tuple[list[Episode], list[MemoryOp]]:
    """Run the model over each planned episode range.

    Returns the (possibly rewritten) episodes plus any ops the model proposed.
    Shadow mode returns the episodes untouched and only logs the comparison; the
    write mode merges the draft prose in and hands the ops to ``apply_ops``,
    which validates them before anything can land.
    """

    writes = mode == LLM_EXTRACTION_WRITE
    out: list[Episode] = []
    ops: list[MemoryOp] = []

    for episode in episodes:
        pairs = _slice_pairs(events, episode.start_turn, episode.end_turn)
        result = llm_extract.extract(
            [event for _turn, event in pairs],
            turns=[turn for turn, _event in pairs],
            conversation_id=conversation_id,
            active_memories=active_memories,
        )
        if result is not None and writes:
            out.append(_merge_draft(episode, result.episode))
            ops.extend(result.memory_ops)
        else:
            out.append(episode)
        _log_extraction(
            hybrid_store,
            mode=mode,
            phase="episode",
            user_key=user_key,
            space_id=space_id,
            project_id=project_id,
            conversation_id=conversation_id,
            now=now,
            start_turn=episode.start_turn,
            end_turn=episode.end_turn,
            source_message_ids=list(episode.source_message_ids),
            deterministic_episode=episode,
            deterministic_ops=[],
            result=result,
        )
    return out, ops


def _llm_turn_pass(
    hybrid_store: HybridStore,
    turn_pairs: list[tuple[int, ConversationEvent]],
    deterministic_ops: list[MemoryOp],
    *,
    mode: str,
    user_key: str,
    space_id: str,
    project_id: str,
    conversation_id: str,
    active_memories: list[StructuredMemory],
    now: str,
) -> list[MemoryOp]:
    """Model ops for the latest turn, falling back to the planner.

    Without this pass a durable fact would only be model-extracted once its
    turns are evicted into an episode, which on a young conversation may be
    never. When the model returns nothing usable the deterministic ops stay in
    place, so a model outage degrades to today's behaviour.
    """

    result = llm_extract.extract(
        [event for _turn, event in turn_pairs],
        turns=[turn for turn, _event in turn_pairs],
        conversation_id=conversation_id,
        active_memories=active_memories,
        min_events=2,
    )
    _log_extraction(
        hybrid_store,
        mode=mode,
        phase="turn",
        user_key=user_key,
        space_id=space_id,
        project_id=project_id,
        conversation_id=conversation_id,
        now=now,
        start_turn=turn_pairs[0][0] if turn_pairs else 0,
        end_turn=turn_pairs[-1][0] if turn_pairs else 0,
        source_message_ids=[e.event_id for _t, e in turn_pairs if e.event_id],
        deterministic_episode=None,
        deterministic_ops=deterministic_ops,
        result=result,
    )
    if mode == LLM_EXTRACTION_WRITE and result is not None and result.memory_ops:
        return list(result.memory_ops)
    return deterministic_ops


def _apply_ops_by_scope(
    hybrid_store: HybridStore,
    ops: list[MemoryOp],
    *,
    user_key: str,
    space_id: str,
    project_id: str,
    conversation_id: str,
    now: str,
    valid_source_ids: set[str] | None = None,
) -> dict[str, int]:
    """Route each proposal to the store that owns its scope (§2, §23).

    Project and conversation records land in the project sidecar; ``global``
    records land at the user root through :class:`GlobalMemoryStore`, so a
    durable preference is recoverable from any thread. Every bucket still goes
    through the same validated ``apply_ops`` mutation gate -- scope routing only
    decides *where* a record lives, never *whether* it is allowed in.
    """

    buckets = scope_mod.partition_by_scope(
        ops,
        user_key=user_key,
        project_id=project_id,
        conversation_id=conversation_id,
    )
    global_store = GlobalMemoryStore(hybrid_store.base)
    targets = (
        (SCOPE_GLOBAL, global_store, user_key, user_key),
        (SCOPE_CONVERSATION, hybrid_store, conversation_id, ""),
        (SCOPE_PROJECT, hybrid_store, project_id, ""),
    )
    counts: dict[str, int] = {}
    for scope_type, target, scope_id, user_id in targets:
        bucket = buckets.get(scope_type) or []
        if not bucket:
            continue
        target.apply_ops(
            user_key,
            space_id,
            project_id,
            bucket,
            conversation_id=conversation_id,
            now=now,
            valid_source_ids=valid_source_ids,
            scope_type=scope_type,
            scope_id=scope_id,
            user_id=user_id,
        )
        counts[scope_type] = len(bucket)
    return counts


# ----- End-of-run pipeline (§28, §45) -----


def process_run_end(
    hybrid_store: HybridStore,
    *,
    user_key: str,
    space_id: str,
    project_id: str,
    conversation_id: str,
    state: str = "done",
    now: str | None = None,
    budget_tokens: int | None = None,
) -> dict[str, Any]:
    """End-of-run memory work. Returns a small summary dict.

    Steps: plan eviction -> build episodes (deterministic boundaries, optionally
    model-authored prose) -> apply memory ops (planner or model, always
    validated) -> update working memory. Idempotent: the coverage watermark
    prevents an episode being rebuilt for a turn range already covered.

    The optional model pass is gated by ``llm_extraction_mode()``: ``off`` keeps
    this fully deterministic, ``shadow`` runs the model and logs a comparison
    without writing, ``write`` lets the model author prose/ops with the
    deterministic planner as the fallback.
    """

    now = now or _utc_now()
    base = hybrid_store.base
    events = load_events(base, user_key, space_id, project_id)
    summary: dict[str, Any] = {"episodes": 0, "memory_ops": 0, "state": state}
    if not events:
        return summary

    mode = llm_extraction_mode()
    summary["llm_extraction"] = mode
    active_memories = (
        hybrid_store.read_active_memories(user_key, space_id, project_id)
        if mode != LLM_EXTRACTION_OFF
        else []
    )
    llm_ops: list[MemoryOp] = []

    # 1. Boundary-aware eviction into episodes (§6-7).
    covered = hybrid_store.read_covered_through_turn(
        user_key, space_id, project_id
    )
    if covered > len(events):
        # Transcript was reset/imported; start a fresh coverage epoch.
        covered = 0
    plan = extractor.plan_eviction(
        events,
        covered_through_turn=covered,
        budget_tokens=budget_tokens or recent_token_budget(),
        soft=soft_threshold(),
        hard=hard_threshold(),
    )
    summary["eviction"] = {
        "total_tokens": plan.total_tokens,
        "recent_start_turn": plan.recent_start_turn,
        "evict_through_turn": plan.evict_through_turn,
        "forced": plan.forced,
        "reason": plan.reason,
    }
    if plan.evict_through_turn > covered:
        episodes = extractor.build_episodes(
            events,
            start_turn=covered + 1,
            end_turn=plan.evict_through_turn,
            conversation_id=conversation_id,
            now=now,
        )
        if episodes and mode != LLM_EXTRACTION_OFF:
            episodes, llm_ops = _llm_episode_pass(
                hybrid_store,
                episodes,
                events,
                mode=mode,
                user_key=user_key,
                space_id=space_id,
                project_id=project_id,
                conversation_id=conversation_id,
                active_memories=active_memories,
                now=now,
            )
        if episodes:
            hybrid_store.append_episodes(
                user_key, space_id, project_id, episodes
            )
            for episode in episodes:
                vector.index_episode(
                    user_key,
                    space_id,
                    project_id,
                    episode.id,
                    episode.source_text(),
                )
            summary["episodes"] = len(episodes)
        hybrid_store.write_covered_through_turn(
            user_key, space_id, project_id, plan.evict_through_turn, now=now
        )

    # 2. Structured memory from the latest turn only (§28, §29).
    latest_run = events[-1].run_id
    turn_events = [e for e in events if e.run_id == latest_run]
    turn_pairs = [
        (turn, event)
        for turn, event in enumerate(events, start=1)
        if event.run_id == latest_run and (event.content or "").strip()
    ]
    ops = extractor.propose_memory_ops(turn_events)
    if mode != LLM_EXTRACTION_OFF and llm_extraction_turn_ops():
        ops = _llm_turn_pass(
            hybrid_store,
            turn_pairs,
            ops,
            mode=mode,
            user_key=user_key,
            space_id=space_id,
            project_id=project_id,
            conversation_id=conversation_id,
            active_memories=active_memories,
            now=now,
        )
    # In `on` mode the episodes may also have proposed durable ops; both sets go
    # through the same validated mutation gate.
    if mode == LLM_EXTRACTION_WRITE:
        ops = [*ops, *llm_ops]
    if ops:
        scope_counts = _apply_ops_by_scope(
            hybrid_store,
            ops,
            user_key=user_key,
            space_id=space_id,
            project_id=project_id,
            conversation_id=conversation_id,
            now=now,
            valid_source_ids=_known_message_ids(events),
        )
        summary["memory_ops"] = len(ops)
        summary["memory_ops_by_scope"] = scope_counts

    # 3. Working memory (§14).
    previous = hybrid_store.read_working_memory(user_key, space_id, project_id)
    user_prompt = next(
        (e.content for e in turn_events if e.role == "user"), ""
    )
    assistant_text = next(
        (e.content for e in reversed(turn_events) if e.role == "assistant"), ""
    )
    working = extractor.update_working_memory(
        previous,
        conversation_id=conversation_id,
        user_prompt=user_prompt,
        assistant_text=assistant_text,
        status=state,
        ops=ops,
        now=now,
    )
    hybrid_store.write_working_memory(user_key, space_id, project_id, working)

    return summary


def schedule_process_run_end(
    hybrid_store: HybridStore,
    *,
    user_key: str,
    space_id: str,
    project_id: str,
    conversation_id: str,
    state: str = "done",
) -> None:
    """Run :func:`process_run_end` off the response path (§28).

    ``on_run_end`` is synchronous, so when background mode is on we hand the
    work to a daemon thread. Failures are swallowed and logged; memory work must
    never surface to the user.
    """

    if not extraction_enabled():
        return

    if not background_pipeline() and llm_extract.available():
        # The whole point of the thread is to keep extraction off the response
        # path (§28); with the model pass on, running it inline would put a
        # blocking LLM call on that path. Warn rather than silently do it.
        logger.warning(
            "hybrid: LLM extraction is enabled but UNDISCLOSED_HYBRID_BACKGROUND"
            " is off; the model pass will run on the response path"
        )

    if not background_pipeline():
        try:
            process_run_end(
                hybrid_store,
                user_key=user_key,
                space_id=space_id,
                project_id=project_id,
                conversation_id=conversation_id,
                state=state,
            )
        except Exception:  # noqa: BLE001
            logger.warning("hybrid: run-end pipeline failed", exc_info=True)
        return

    def _worker() -> None:
        try:
            process_run_end(
                hybrid_store,
                user_key=user_key,
                space_id=space_id,
                project_id=project_id,
                conversation_id=conversation_id,
                state=state,
            )
        except Exception:  # noqa: BLE001
            logger.warning("hybrid: run-end pipeline failed", exc_info=True)

    threading.Thread(
        target=_worker, name="hybrid-memory-pipeline", daemon=True
    ).start()
