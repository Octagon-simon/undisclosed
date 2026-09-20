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

"""Optional LLM extraction pass: episode draft + proposed memory ops.

``hybrid_memory.md`` treats extraction as a *model* job (§12 "extraction
model", §30 "episode generation prompt requirements"); :mod:`extractor` is
deterministic by design. This module adds the model path without touching the
storage or mutation contract:

- the deterministic planner still decides *where* a slice begins and ends,
- this pass only rewrites the prose and proposes ops,
- every proposed op passes through ``HybridStore.apply_ops`` (schema, type,
  target and provenance checks) before anything can be written,
- the deterministic planner stays available as the fallback whenever the model
  is missing, fails, or returns something that does not parse.

Rollout is staged (see :func:`app.memory.hybrid.config.llm_extraction_mode`):
``off`` (default) -> ``shadow`` (run + log a comparison, never write) -> ``on``
(authoritative, deterministic fallback).

It runs off the response path on the daemon worker started by
``engine.schedule_process_run_end``, so it uses the *synchronous* CAMEL path
(``ChatAgent.step``): there is no event loop on that thread to await, and a
plain blocking call is exactly what a worker thread can afford.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

from app.memory.events import ConversationEvent
from app.memory.hybrid import config
from app.memory.hybrid import extractor
from app.memory.hybrid import text as T
from app.memory.hybrid.schema import (
    MEMORY_TYPES,
    EpisodeDraft,
    ExtractionResult,
    MemoryOp,
    StructuredMemory,
)

logger = logging.getLogger("memory.hybrid.llm_extract")

#: A blocking ``(system_prompt, user_prompt) -> raw_text`` callable.
Completer = Callable[[str, str], str]

_SYSTEM = """You are the memory-extraction model for a long-running coding agent.

You are given a slice of a conversation as messages tagged with their turn
number and message id. Produce exactly TWO things:

1. "episode": a compressed, human-readable summary of this slice.
2. "memoryOps": durable state changes worth keeping beyond this slice.

Rules:
- Use ONLY information present in the provided messages. Never invent facts,
  ids, names, numbers, files or decisions.
- Distinguish durable information (decisions, constraints, preferences, goals,
  stable facts) from temporary chatter. Emit nothing for transient detail.
- If a decision changes inside this slice, emit an UPSERT for the same key with
  the new value; the store versions and supersedes the old record itself.
- Every op MUST carry "sourceMessageIds": one or more message ids from the
  messages you were shown that directly support it. An op without a source id,
  or citing an id you were not given, is discarded.
- "type" is one of: fact, preference, decision, constraint, goal.
- "key" is a short, stable, lower_snake_case noun for the concept
  (e.g. "database", "deployment_target", "test_runner"), never a sentence.
- "value" is short and concrete, never a prose paragraph.
- Prefer a few high-confidence ops over many speculative ones. An empty list is
  a perfectly good answer.
- Respond with a single JSON object and NOTHING else: no markdown fence, no
  preamble, no explanation.

JSON shape:
{
  "episode": {
    "title": "<short title>",
    "summary": "<objective; what was discussed; decisions; open questions>",
    "objective": "<what the user was trying to achieve>",
    "topic": "<comma-separated key terms>",
    "importance": <number 0.0-1.0>,
    "decisions": ["<decision stated in the slice>"]
  },
  "memoryOps": [
    {"op": "UPSERT", "type": "decision", "key": "database",
     "value": "PostgreSQL", "reason": "<why>", "sourceMessageIds": ["msg_12"]}
  ]
}
"""

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)

# Ops the model may propose. Anything else is dropped before it reaches the
# store, so an unknown verb can never become a mutation.
_KNOWN_OPS = frozenset({"UPSERT", "SUPERSEDE", "DELETE", "MERGE"})


def available() -> bool:
    """True when the model pass is configured to run (shadow or on)."""

    return config.llm_extraction_enabled()


def worth_extracting(
    events: list[ConversationEvent], *, min_events: int | None = None
) -> bool:
    """Cheap deterministic gate before spending a model call.

    ``research1.md`` suggests asking "is this episode memory-worthy?" first so a
    boring stretch of chatter costs nothing. We require a minimum number of
    non-empty messages *and* at least one substantive user message (the existing
    :func:`extractor.is_worthy` cue check).
    """

    threshold = (
        min_events if min_events is not None else config.llm_extraction_min_events()
    )
    non_empty = [e for e in events if (e.content or "").strip()]
    if len(non_empty) < threshold:
        return False
    return any(
        e.role == "user" and extractor.is_worthy(e.content or "")
        for e in non_empty
    )


def extract(
    slice_events: list[ConversationEvent],
    *,
    turns: list[int] | None = None,
    conversation_id: str = "",
    active_memories: list[StructuredMemory] | None = None,
    completer: Completer | None = None,
    min_events: int | None = None,
) -> ExtractionResult | None:
    """Run one extraction pass over ``slice_events``.

    ``turns`` optionally carries the transcript position of each event (used to
    number messages in the prompt); it is aligned 1:1 with ``slice_events``.

    Returns ``None`` (never raises) when the model pass is off, the slice is not
    worth a call, no model is available, the call fails, or the response does
    not parse. Callers treat ``None`` as "fall back to the deterministic
    planner", which is the whole point of the fallback contract.
    """

    if not slice_events:
        return None

    call = completer
    if call is None:
        if not available():
            return None
        call = _default_completer()
        if call is None:
            return None

    pairs: list[tuple[int, ConversationEvent]] = [
        (turns[i] if turns and i < len(turns) else i + 1, event)
        for i, event in enumerate(slice_events)
        if (event.content or "").strip()
    ][: config.llm_extraction_max_events()]
    if not pairs:
        return None

    events = [event for _turn, event in pairs]
    if not worth_extracting(events, min_events=min_events):
        return None

    prompt = _build_user_prompt(
        pairs,
        conversation_id=conversation_id,
        active_memories=active_memories or [],
    )
    try:
        raw = call(_SYSTEM, prompt)
    except Exception:  # noqa: BLE001 - model failure must degrade, not break
        logger.warning("hybrid: LLM extraction call failed", exc_info=True)
        return None

    allowed = {e.event_id for e in events if e.event_id}
    return parse_extraction(raw, allowed_source_ids=allowed)


# ----- Prompt -----


def _render_message(turn: int, event: ConversationEvent) -> str:
    content = T.truncate(
        T.collapse(event.content or ""), config.llm_extraction_max_chars()
    )
    return f"<turn {turn} | id={event.event_id} | {event.role}> {content}"


def _build_user_prompt(
    pairs: list[tuple[int, ConversationEvent]],
    *,
    conversation_id: str,
    active_memories: list[StructuredMemory],
) -> str:
    lines: list[str] = [f"Conversation: {conversation_id}"]
    lines.append("")
    lines.append("Message slice:")
    for turn, event in pairs:
        lines.append(_render_message(turn, event))

    lines.append("")
    lines.append(
        "Known durable memory already stored (cite one of these ids ONLY if you "
        "need to supersede/delete/merge an existing record):"
    )
    if active_memories:
        for memory in active_memories[:60]:
            lines.append(
                f"- id={memory.id} {memory.type} {memory.key} = {memory.value}"
            )
    else:
        lines.append("- (none)")

    lines.append("")
    lines.append("Extract now. Reply with the JSON object only.")
    return "\n".join(lines)


# ----- Response parsing / validation -----


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
    return out


def _extract_json(raw: str) -> dict[str, Any] | None:
    """Tolerantly pull the first JSON object out of a model response."""

    if not raw:
        return None
    text = raw.strip()
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except (ValueError, TypeError):
            return None
    return parsed if isinstance(parsed, dict) else None


def _coerce_op(
    payload: Any, *, allowed_source_ids: set[str] | None
) -> MemoryOp | None:
    """Build a :class:`MemoryOp` from one model row, or drop it.

    This is the *structural* half of the guardrail (known verb, known type,
    non-empty value, provenance present and inside the slice). It deliberately
    says nothing about whether the op is semantically right -- the store
    remains the mutation authority for that.
    """

    if not isinstance(payload, dict):
        return None
    op = MemoryOp(
        op=str(payload.get("op") or "").strip().upper(),
        type=str(payload.get("type") or "").strip().lower(),
        key=str(payload.get("key") or "").strip(),
        value=str(payload.get("value") or "").strip(),
        memory_id=(
            str(payload.get("memory_id") or payload.get("memoryId") or "").strip()
        ),
        reason=str(payload.get("reason") or "").strip(),
        confidence=_coerce_float(payload.get("confidence"), 0.6),
        source_message_ids=_coerce_ids(
            payload.get("source_message_ids") or payload.get("sourceMessageIds")
        ),
    )
    if op.op not in _KNOWN_OPS:
        return None
    if op.op == "UPSERT":
        if op.type not in MEMORY_TYPES or not op.value:
            return None
    elif op.op in {"SUPERSEDE", "DELETE"}:
        if not op.memory_id:
            return None
    elif op.op == "MERGE":
        if not op.memory_id or not op.value:
            return None
    # Provenance is mandatory: an op the model cannot tie back to a message it
    # was actually shown is exactly the invented memory we must not persist.
    if not op.source_message_ids:
        return None
    if allowed_source_ids is not None and not any(
        sid in allowed_source_ids for sid in op.source_message_ids
    ):
        return None
    return op


def parse_extraction(
    raw: str, *, allowed_source_ids: set[str] | None = None
) -> ExtractionResult | None:
    """Parse a model response into a validated :class:`ExtractionResult`."""

    payload = _extract_json(raw)
    if payload is None:
        return None

    episode = EpisodeDraft.from_dict(payload.get("episode")) or EpisodeDraft()
    episode.importance = max(0.0, min(1.0, episode.importance))

    raw_ops = payload.get("memory_ops") or payload.get("memoryOps")
    ops: list[MemoryOp] = []
    for row in raw_ops if isinstance(raw_ops, list) else []:
        op = _coerce_op(row, allowed_source_ids=allowed_source_ids)
        if op is not None:
            ops.append(op)
        if len(ops) >= config.llm_extraction_max_ops():
            break

    if not episode.summary.strip() and not ops:
        return None
    return ExtractionResult(episode=episode, memory_ops=ops)


# ----- Model access -----


def _response_text(response: Any) -> str:
    """Best-effort text out of a CAMEL chat response.

    The cached chat model may be configured for streaming, in which case the
    content arrives by iterating the response rather than on ``.msg``. Both
    shapes are handled; anything else yields "".
    """

    try:
        text = getattr(getattr(response, "msg", None), "content", "") or ""
    except Exception:  # noqa: BLE001
        text = ""
    if text.strip():
        return text

    try:
        chunks = list(response)
    except TypeError:
        return ""
    parts: list[str] = []
    for chunk in chunks:
        try:
            parts.append(getattr(getattr(chunk, "msg", None), "content", "") or "")
        except Exception:  # noqa: BLE001
            continue
    return "".join(parts)


def _default_completer() -> Completer | None:
    """Blocking completer backed by the model the user is chatting with.

    Lazily imports the agent layer: importing it at module import time would
    pull the whole agent stack into the memory package (and risk an import
    cycle), while this function only ever runs on the end-of-run worker.
    """

    try:
        from app.agent.agent_model import get_last_model
    except Exception:  # noqa: BLE001
        logger.debug("hybrid: agent layer unavailable for extraction", exc_info=True)
        return None

    model = get_last_model()
    if model is None:
        return None

    def _complete(system: str, user: str) -> str:
        from camel.agents import ChatAgent
        from camel.messages import BaseMessage

        agent = ChatAgent(
            BaseMessage.make_assistant_message(
                role_name="MemoryExtractor", content=system
            ),
            model=model,
        )
        response = agent.step(user)
        text = _response_text(response)
        if not text.strip():
            raise RuntimeError("empty model response")
        return text

    return _complete
