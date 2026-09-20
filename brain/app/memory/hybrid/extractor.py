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

"""Boundary-aware extraction: eviction planning, episodes, memory ops (§6-14).

Everything here is deterministic and model-free, so it is safe to run at end of
run without a bill or a latency spike. The extractor:

- decides which older messages have fallen out of the recent window and *where*
  to cut so an episode never slices through the middle of a coherent topic
  (:func:`plan_eviction`, :func:`find_boundary`),
- turns an evicted turn range into independent episodes with source links
  (:func:`build_episodes`), never a recursive master summary (§8),
- proposes structured-memory operations and working-memory state, which the
  store validates before applying (§12, §14).

It must never invent information: summaries are extractive (built from verbatim
fragments plus terms that actually occur), and a fact/decision is only proposed
when an explicit linguistic cue is present.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from app.memory.events import ConversationEvent
from app.memory.hybrid import canonical
from app.memory.hybrid import text as T
from app.memory.hybrid.schema import Episode, MemoryOp, WorkingMemory
from app.memory.hybrid.config import (
    episode_max_turns,
    episode_summary_max_chars,
)

# ----- Eviction planning (§5-6) -----


@dataclass
class EvictionPlan:
    """Which messages are now outside the recent window and where to cut."""

    total_tokens: int
    recent_start_turn: int
    evict_through_turn: int
    forced: bool = False
    boundary_turn: int | None = None
    reason: str = ""

    @property
    def has_work(self) -> bool:
        return self.evict_through_turn >= 1


def _event_tokens(event: ConversationEvent) -> int:
    return T.tokenize_len(event.content)


def plan_eviction(
    events: list[ConversationEvent],
    *,
    covered_through_turn: int,
    budget_tokens: int,
    soft: float,
    hard: float,
) -> EvictionPlan:
    """Decide how much of the transcript may leave the active window.

    Walks newest-first until the token budget is exceeded; everything older is
    the *candidate* eviction region. Eviction only proceeds past what an episode
    already covers, and prefers a natural boundary over a hard token cut. When
    no boundary exists it waits until the hard threshold, then falls back to a
    deterministic token cut so the window can never overflow (§5).
    """

    indexed = [
        (i, e)
        for i, e in enumerate(events, start=1)
        if (e.content or "").strip()
    ]
    total_tokens = sum(_event_tokens(e) for _i, e in indexed)
    if not indexed:
        return EvictionPlan(0, 1, covered_through_turn, reason="empty")

    used = 0
    recent_start_turn = indexed[-1][0]
    for turn, event in reversed(indexed):
        used += _event_tokens(event)
        recent_start_turn = turn
        if used >= budget_tokens:
            break

    candidate_end = recent_start_turn - 1
    if candidate_end <= covered_through_turn:
        return EvictionPlan(
            total_tokens,
            recent_start_turn,
            covered_through_turn,
            reason="window covers everything new",
        )

    hard_limit = int(budget_tokens * hard)
    soft_limit = int(budget_tokens * soft)
    if total_tokens >= hard_limit:
        return EvictionPlan(
            total_tokens,
            recent_start_turn,
            candidate_end,
            forced=True,
            reason="hard threshold reached; deterministic cut",
        )
    if total_tokens >= soft_limit:
        boundary = find_boundary(events, covered_through_turn + 1, candidate_end)
        if boundary is not None and boundary > covered_through_turn:
            return EvictionPlan(
                total_tokens,
                recent_start_turn,
                boundary,
                boundary_turn=boundary,
                reason="semantic boundary",
            )
        return EvictionPlan(
            total_tokens,
            recent_start_turn,
            covered_through_turn,
            reason="soft threshold, no boundary yet",
        )
    return EvictionPlan(
        total_tokens,
        recent_start_turn,
        covered_through_turn,
        reason="below soft threshold",
    )


# End-of-segment cues in an assistant message ("done", "that's it", ...). A
# boundary after such a message is a task boundary (§6, priority 2).
_COMPLETION_RE = re.compile(
    r"\b(done|completed|finished|implemented|all set|that'?s it|wrapped up|"
    r"fixed|resolved|shipped)\b",
    re.IGNORECASE,
)


def _user_turns(events: list[ConversationEvent]) -> list[tuple[int, str]]:
    return [
        (i, e.content or "")
        for i, e in enumerate(events, start=1)
        if (e.content or "").strip() and e.role == "user"
    ]


def find_boundary(
    events: list[ConversationEvent], start_turn: int, end_turn: int
) -> int | None:
    """Latest natural boundary in ``[start_turn, end_turn]``, or None.

    A boundary is the last message of a coherent segment: either a user message
    that opens a new topic (low keyword overlap with the previous user message),
    or an assistant message that signals task completion. Returns the highest
    such turn so eviction keeps as much recent context as possible without
    cutting mid-topic (§6, §33).
    """

    if end_turn < start_turn:
        return None
    users = [(t, txt) for t, txt in _user_turns(events) if start_turn <= t <= end_turn]
    best: int | None = None

    for prev, cur in zip(users, users[1:]):
        prev_turn, prev_text = prev
        cur_turn, cur_text = cur
        if T.keyword_overlap(prev_text, cur_text) < 0.2:
            boundary = cur_turn - 1
            if boundary >= start_turn and (
                best is None or boundary > best
            ):
                best = boundary

    for turn, event in _indexed(events):
        if not (start_turn <= turn <= end_turn):
            continue
        if event.role == "assistant" and _COMPLETION_RE.search(
            event.content or ""
        ):
            if best is None or turn > best:
                best = turn

    return best


def _indexed(
    events: list[ConversationEvent],
) -> list[tuple[int, ConversationEvent]]:
    return [
        (i, e)
        for i, e in enumerate(events, start=1)
        if (e.content or "").strip()
    ]


# ----- Episode building (§7, §9, §30) -----

_KEY_NOUNS = (
    "database", "db", "framework", "language", "library", "package",
    "package manager", "orm", "port", "timeout", "api", "endpoint", "url",
    "storage", "cache", "queue", "auth", "authentication", "ui", "frontend",
    "backend", "test runner", "build tool", "deployment", "hosting", "bucket",
    "model", "provider", "license", "distribution", "format",
)


def _key_from_text(text: str) -> str:
    """Pick a stable key noun that literally occurs in the text (§13)."""

    lowered = (text or "").lower()
    for noun in _KEY_NOUNS:
        if re.search(rf"\b{re.escape(noun)}\b", lowered):
            return canonical.normalize_key(noun)
    return ""


def _topic_terms(events: Iterable[ConversationEvent], *, limit: int = 6) -> str:
    counter: Counter[str] = Counter()
    for event in events:
        counter.update(
            t for t in T.tokenize(event.content or "") if len(t) > 2
        )
    return ", ".join(term for term, _ in counter.most_common(limit))


def _gist(text: str, max_chars: int) -> str:
    body = T.collapse(text)
    return T.truncate(body, max_chars)


def build_episode(
    slice_events: list[ConversationEvent],
    *,
    conversation_id: str,
    start_turn: int,
    end_turn: int,
    now: str,
) -> Episode:
    """Summarize one coherent slice into an independent episode (extractively)."""

    users = [e for e in slice_events if e.role == "user" and e.content.strip()]
    assistants = [
        e for e in slice_events if e.role == "assistant" and e.content.strip()
    ]
    source_ids = [
        e.event_id for e in slice_events if (e.content or "").strip()
    ]

    title_source = users[0].content if users else (
        slice_events[0].content if slice_events else ""
    )
    title = T.truncate(T.collapse(title_source), 80) or "Conversation segment"

    lines: list[str] = []
    if users:
        lines.append(f"Objective: {_gist(users[0].content, 240)}")

    discussed: list[str] = []
    seen: set[str] = set()
    for event in assistants:
        gist = _gist(event.content, 200)
        fingerprint = gist[:60].lower()
        if fingerprint and fingerprint not in seen:
            seen.add(fingerprint)
            discussed.append(gist)
        if len(discussed) >= 3:
            break
    if discussed:
        lines.append("Discussed: " + " | ".join(discussed))
    else:
        # No assistant text: fall back to the user's own later messages.
        for event in users[1:4]:
            discussed.append(_gist(event.content, 200))
        if discussed:
            lines.append("Discussed: " + " | ".join(discussed))

    ops = propose_memory_ops(slice_events)
    decisions = [op.value for op in ops if op.type == "decision"]
    constraints = [op.value for op in ops if op.type == "constraint"]
    if decisions:
        lines.append("Decisions: " + " | ".join(dict.fromkeys(decisions)))
    if constraints:
        lines.append("Constraints: " + " | ".join(dict.fromkeys(constraints)))

    identifiers: list[str] = []
    for event in slice_events:
        for entity in sorted(T.entities(event.content or "")):
            if entity not in identifiers:
                identifiers.append(entity)
    if identifiers:
        lines.append("Key values: " + ", ".join(identifiers[:12]))

    questions = [
        _gist(e.content, 160)
        for e in users
        if "?" in (e.content or "")
    ]
    if questions:
        lines.append("Open questions: " + " | ".join(questions[:3]))

    summary = T.truncate("\n".join(lines), episode_summary_max_chars())

    importance = 0.4
    if decisions:
        importance += 0.2
    if constraints:
        importance += 0.15
    if identifiers:
        importance += 0.1
    if len(source_ids) >= 6:
        importance += 0.05
    importance = min(1.0, importance)

    return Episode(
        id=f"ep_{conversation_id}_{start_turn}_{end_turn}",
        conversation_id=conversation_id,
        start_turn=start_turn,
        end_turn=end_turn,
        title=T.collapse(title),
        topic=_topic_terms(slice_events),
        summary=summary,
        source_message_ids=source_ids,
        importance=importance,
        created_at=now,
    )


def build_episodes(
    events: list[ConversationEvent],
    *,
    start_turn: int,
    end_turn: int,
    conversation_id: str,
    now: str,
    max_turns: int | None = None,
) -> list[Episode]:
    """Split ``[start_turn, end_turn]`` into episodes at boundaries (§33).

    Priority: natural boundary, then a hard ``max_turns`` cap so a single
    runaway topic still yields multiple independent episodes.
    """

    cap = max_turns or episode_max_turns()
    pairs = [
        (t, e) for t, e in _indexed(events) if start_turn <= t <= end_turn
    ]
    if not pairs:
        return []

    def _emit(segment: list[tuple[int, ConversationEvent]]) -> Episode:
        return build_episode(
            [event for _t, event in segment],
            conversation_id=conversation_id,
            start_turn=segment[0][0],
            end_turn=segment[-1][0],
            now=now,
        )

    episodes: list[Episode] = []
    segment: list[tuple[int, ConversationEvent]] = [pairs[0]]
    for pair in pairs[1:]:
        turn, event = pair
        prev_event = segment[-1][1]
        starts_new_topic = (
            event.role == "user"
            and prev_event.role == "assistant"
            and T.keyword_overlap(prev_event.content, event.content) < 0.2
        )
        if (turn - segment[0][0] >= cap) or starts_new_topic:
            episodes.append(_emit(segment))
            segment = [pair]
        else:
            segment.append(pair)
    episodes.append(_emit(segment))
    return episodes


# ----- Structured memory extraction (§10, §12-13, §29) -----

_DECISION_RES = (
    re.compile(
        r"\b(?:we(?:'ll| will| should)?|i(?:'ll| will| want to)?|let'?s)\s+"
        r"(?:use|go with|switch to|adopt|pick|choose|standardize on)\s+"
        r"(?P<value>[^.\n;]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:switch(?:ing)?|chang(?:e|ing)|mov(?:e|ing))\s+(?:from\s+"
        r"(?P<old>[^.\n;]+?)\s+)?to\s+(?P<value>[^.\n;]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:decided|chose|choosing|settle[d]?\s+on|opt(?:ing)?\s+for)\s+"
        r"(?:on\s+)?(?P<value>[^.\n;]+)",
        re.IGNORECASE,
    ),
)
_CONSTRAINT_RES = (
    re.compile(
        r"\b(?:do not|don'?t|must not|mustn'?t|never|avoid|shouldn'?t)\s+"
        r"(?P<value>[^.\n;]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:must|has to|have to|need to)\s+be\s+(?P<value>[^.\n;]+)",
        re.IGNORECASE,
    ),
)
_PREFERENCE_RES = (
    re.compile(
        r"\bi\s+(?:prefer|like|always|usually|want)\s+(?P<value>[^.\n;]+)",
        re.IGNORECASE,
    ),
    re.compile(r"\bprefer(?:red|s)?\s+(?P<value>[^.\n;]+)", re.IGNORECASE),
)
_GOAL_RES = (
    re.compile(
        r"\b(?:goal is|objective is|the point is|we need to|i need to|"
        r"we want to)\s+(?P<value>[^.\n;]+)",
        re.IGNORECASE,
    ),
)

_LOW_VALUE = frozenset(
    {
        "ok", "okay", "sure", "thanks", "thank you", "yes", "no", "lol",
        "continue", "go on", "got it", "cool", "nice", "great", "hi", "hello",
        "hey",
    }
)


def is_worthy(text: str) -> bool:
    """False for greetings/acks/one-word chatter (§29)."""

    stripped = T.collapse(text).strip().lower().strip(".!")
    if not stripped:
        return False
    if stripped in _LOW_VALUE:
        return False
    if len(stripped) < 6:
        return False
    return True


def _clean_value(value: str, *, max_chars: int = 120) -> str:
    cleaned = T.collapse(value).strip(" .,;:-")
    # Cut a trailing clause that usually is a reason, not the decision value.
    cleaned = re.split(r"\s+(?:because|since|so that|but|although)\s+", cleaned)[
        0
    ]
    return T.truncate(cleaned.strip(), max_chars)


def propose_memory_ops(
    events: list[ConversationEvent],
) -> list[MemoryOp]:
    """Propose structured-memory ops from user statements (§12, §29).

    Only *user* messages are mined and only when an explicit cue matches, so the
    assistant's own prose cannot become durable memory. Keys are canonicalized
    and, when no stable key noun occurs, the concept noun in the value is used;
    otherwise the proposal is dropped rather than stored under a guessy key.
    """

    ops: list[MemoryOp] = []
    seen: set[str] = set()

    for event in events:
        if event.role != "user":
            continue
        text = event.content or ""
        if not is_worthy(text):
            continue

        for pattern in _DECISION_RES:
            for match in pattern.finditer(text):
                value = _clean_value(match.group("value"))
                if not value:
                    continue
                key = _key_from_text(text) or _key_from_text(value)
                if not key:
                    continue
                op = _make_op("decision", key, value, event)
                if _remember(ops, seen, op):
                    pass

        for pattern in _CONSTRAINT_RES:
            for match in pattern.finditer(text):
                value = _clean_value(f"not {match.group('value')}")
                key = _key_from_text(text) or "constraint"
                op = _make_op(
                    "constraint", _constraint_key(key, value), value, event
                )
                _remember(ops, seen, op)

        for pattern in _PREFERENCE_RES:
            for match in pattern.finditer(text):
                value = _clean_value(match.group("value"))
                if not value:
                    continue
                key = _key_from_text(text) or "preference"
                op = _make_op("preference", key, value, event)
                _remember(ops, seen, op)

        for pattern in _GOAL_RES:
            for match in pattern.finditer(text):
                value = _clean_value(match.group("value"))
                if not value:
                    continue
                op = _make_op("goal", "current_goal", value, event)
                _remember(ops, seen, op)

    return ops


def _constraint_key(key: str, value: str) -> str:
    return key if key and key != "constraint" else "constraint"


def _make_op(
    memory_type: str, key: str, value: str, event: ConversationEvent
) -> MemoryOp:
    return MemoryOp(
        op="UPSERT",
        type=memory_type,
        key=key,
        value=value,
        confidence=0.75,
        source_message_ids=[event.event_id],
    )


def _remember(
    ops: list[MemoryOp], seen: set[str], op: MemoryOp
) -> bool:
    fingerprint = canonical.identity(op.type, op.key) + "::" + op.value.lower()
    if fingerprint in seen:
        return False
    seen.add(fingerprint)
    ops.append(op)
    return True


# ----- Working memory (§14) -----

_NEXT_STEP_RE = re.compile(
    r"\b(?:next,?\s+(?:step|up)?|then|after that|now let'?s|let'?s next)\s+"
    r"(?P<value>[^.\n;]+)",
    re.IGNORECASE,
)


def update_working_memory(
    previous: WorkingMemory | None,
    *,
    conversation_id: str,
    user_prompt: str,
    assistant_text: str = "",
    status: str = "",
    ops: list[MemoryOp] | None = None,
    now: str = "",
) -> WorkingMemory:
    """Fold this turn into working memory, keeping it bounded and deduped."""

    base = previous or WorkingMemory(conversation_id=conversation_id)
    ops = ops or []

    decisions = list(base.decisions)
    constraints = list(base.constraints)
    for op in ops:
        if op.type == "decision" and op.value not in decisions:
            decisions.append(op.value)
        elif op.type == "constraint" and op.value not in constraints:
            constraints.append(op.value)

    goal = base.current_goal
    for op in ops:
        if op.type == "goal":
            goal = op.value
            break
    if not goal:
        match = _GOAL_RES[0].search(user_prompt or "")
        if match:
            goal = _clean_value(match.group("value"))

    questions = list(base.open_questions)
    for sentence in T.sentences(user_prompt or ""):
        if "?" in sentence and sentence not in questions:
            questions.append(T.truncate(sentence, 200))

    next_step = base.next_step
    for text in (assistant_text or "", user_prompt or ""):
        match = _NEXT_STEP_RE.search(text)
        if match:
            next_step = _clean_value(match.group("value"))
            break

    return WorkingMemory(
        conversation_id=conversation_id,
        # Never blank the task on a turn that carried no user message (restart /
        # assistant-only finalize): keep the previous task instead.
        current_task=T.truncate(T.collapse(user_prompt), 300)
        or base.current_task,
        current_goal=T.truncate(goal, 300),
        decisions=decisions[-8:],
        constraints=constraints[-8:],
        open_questions=questions[-5:],
        current_status=status or base.current_status,
        next_step=T.truncate(next_step, 300),
        updated_at=now,
    )
