# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
# Portions Copyright 2026 Simon Ugorji. All Rights Reserved.
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
"""Turn-end validation for an agent turn.

The question a turn answers is not "did the model stop talking?" but "is any
execution still owed?" This module derives that from runtime state: open todos,
tool rounds, tool results, and whether the request asked for work at all. The
legacy preamble detector is passed in as one signal instead of being the rule.

Shared by the single agent and by workforce workers, so both accept or nudge a
turn on the same rules.

Pure functions only, so the policy is testable without an agent or a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# A tool result starting with one of these means the action did NOT happen.
_BLOCK_PREFIXES: tuple[str, ...] = ("[system governance]:",)
_FAILURE_PREFIXES: tuple[str, ...] = (
    "error",
    "traceback (most recent call last)",
    "tool execution failed",
    "exception",
    "failed to",
)

# Verbs that make a sentence a work request. Kept small and literal: this only
# matters on a turn where NO tool ran, so a miss costs a stall and a false
# positive costs one extra round trip.
_ACTION_VERBS: frozenset[str] = frozenset(
    {
        "add",
        "apply",
        "bump",
        "change",
        "check",
        "clean",
        "commit",
        "continue",
        "convert",
        "create",
        "delete",
        "deploy",
        "disable",
        "do",
        "document",
        "drop",
        "edit",
        "enable",
        "ensure",
        "fix",
        "go",
        "implement",
        "improve",
        "install",
        "investigate",
        "make",
        "migrate",
        "move",
        "patch",
        "port",
        "print",
        "proceed",
        "read",
        "refactor",
        "remove",
        "rename",
        "replace",
        "revert",
        "review",
        "run",
        "set",
        "setup",
        "show",
        "sort",
        "split",
        "start",
        "stop",
        "test",
        "tidy",
        "trace",
        "update",
        "upgrade",
        "verify",
        "wire",
        "write",
    }
)

# Words that open a question. "how do I fix this" asks for an answer; "fix this"
# asks for work. Checked per sentence so trailing small talk cannot mask an
# imperative clause earlier in the message.
_INTERROGATIVE_OPENERS: frozenset[str] = frozenset(
    {
        "am",
        "are",
        "can",
        "could",
        "did",
        "do",
        "does",
        "explain",
        "has",
        "have",
        "how",
        "is",
        "may",
        "should",
        "tell",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whose",
        "why",
        "will",
        "would",
    }
)

_POLITE_PREFIXES: frozenset[str] = frozenset(
    {
        "also",
        "and",
        "kindly",
        "now",
        "ok",
        "okay",
        "please",
        "sure",
        "then",
        "yeah",
        "yep",
        "yes",
        "yup",
    }
)

_COMPLETION_PATTERN = re.compile(
    r"\b(?:done|completed?|finished|committed|fixed|passing|passes|"
    r"implemented|shipped|resolved|updated|created|added|removed|reverted|"
    r"wrote|written|applied|installed|merged)\b"
)

_NEGATION_PATTERN = re.compile(
    r"\b(?:not|never|no|none|nothing|unable|couldn't|didn't|doesn't|don't|"
    r"won't|can't|cannot|isn't|aren't|wasn't|failed|skipped|undone|pending)\b|"
    r"n't\b"
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

_TOKEN_SPLIT = re.compile(r"[^a-z0-9_']+")


@dataclass(frozen=True)
class ToolOutcome:
    """One tool call's verdict, derived from its result text or payload."""

    tool: str
    failed: bool = False
    blocked: bool = False

    @property
    def is_failure(self) -> bool:
        return self.failed or self.blocked


@dataclass(frozen=True)
class TurnEndState:
    """Everything the accept/continue decision is allowed to look at."""

    question: str
    answer: str
    tool_rounds: int
    todo_open: bool = False
    announce_continue: bool = False
    outcomes: tuple[ToolOutcome, ...] = ()
    # None means "derive it from the question". A workforce worker sets False:
    # its prompt is a structured task, not the user's message, so the
    # zero-tool rule would misfire on a legitimate answer from knowledge.
    action_request: bool | None = None

    @property
    def wants_work(self) -> bool:
        if self.action_request is not None:
            return self.action_request
        return looks_like_action_request(self.question)

    @property
    def failures(self) -> tuple[ToolOutcome, ...]:
        return tuple(o for o in self.outcomes if o.is_failure)

    @property
    def last_outcome(self) -> ToolOutcome | None:
        return self.outcomes[-1] if self.outcomes else None


@dataclass(frozen=True)
class TurnEndDecision:
    """Whether the turn may end, why, and what to send back if it may not."""

    continue_turn: bool
    reason: str = ""
    nudge: str = ""


_NUDGE_TODO = (
    "Your todo list still has an unfinished item, and your last message "
    "described the plan instead of doing it. Continue now: run the next step "
    "with your tools, then update the todos with what actually changed. Do NOT "
    "restate the plan."
)

_NUDGE_ACTION = (
    "Your last message ended the turn without calling a single tool, but the "
    "request asks for work. Do that work now with your tools, then report what "
    "you changed or found. If no action is actually required, say so plainly "
    "and explain why."
)

_NUDGE_COMPLETION = (
    "Your last tool call failed or was blocked, so the work is not done. Do not "
    "claim completion: either retry with a corrected approach, or tell the user "
    "exactly what failed and what you need from them."
)

_NUDGE_ANNOUNCE = (
    "Continue now. Actually perform the action you just described, using your "
    "tools, do NOT restate the plan. Do the work, then report what you changed "
    "or found."
)

_NUDGE_REPORT = (
    "You ended your turn without a final answer. Report now, in a short "
    "concrete summary, what you did and found. If the task is complete, say so "
    "plainly; otherwise finish the remaining steps first."
)


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_SPLIT.split(text.lower()) if t]


def _strip_polite_prefix(tokens: list[str]) -> list[str]:
    while tokens and tokens[0] in _POLITE_PREFIXES:
        tokens = tokens[1:]
    # "can you fix this" is a request; "can it be fixed" is a question.
    if (
        len(tokens) > 1
        and tokens[0] in {"can", "could", "would", "will"}
        and tokens[1] == "you"
    ):
        tokens = tokens[2:]
    return tokens


def looks_like_action_request(question: str) -> bool:
    """True when the message contains an imperative clause asking for work.

    Deliberately conservative: any imperative clause anywhere in the message
    counts, so "okay. commit what we have. developer agent is the workforce
    mode right?" is a work request. Pure questions ("how do I fix this?") are
    not, because there the user wants an answer, not a change.
    """
    text = (question or "").strip()
    if not text:
        return False
    for sentence in _SENTENCE_SPLIT.split(text):
        tokens = _strip_polite_prefix(_tokens(sentence))
        if not tokens:
            continue
        head = tokens[0]
        if head in _INTERROGATIVE_OPENERS:
            continue
        if head in _ACTION_VERBS:
            return True
    return False


def classify_tool_result(tool: str, result: Any) -> ToolOutcome:
    """Verdict for one tool call.

    Prefix-only matching, so grep output that merely CONTAINS the word "error"
    is not counted as a failure.
    """
    if isinstance(result, dict):
        blocked = bool(result.get("blocked")) or (
            str(result.get("status", "")).strip().lower() == "blocked"
        )
        failed = bool(result.get("error")) or result.get("success") is False
        return ToolOutcome(tool=tool, failed=failed, blocked=blocked)

    text = str(result if result is not None else "").strip()
    head = text[:200].lower()
    if head.startswith(_BLOCK_PREFIXES):
        return ToolOutcome(tool=tool, blocked=True)
    if head.startswith(_FAILURE_PREFIXES):
        return ToolOutcome(tool=tool, failed=True)
    return ToolOutcome(tool=tool)


def classify_tool_records(records: Any) -> tuple[ToolOutcome, ...]:
    """Normalize CAMEL tool records (objects or dicts) into outcomes."""
    outcomes: list[ToolOutcome] = []
    for record in records or ():
        if isinstance(record, dict):
            fn = record.get("function")
            tool = str(
                record.get("tool_name")
                or record.get("name")
                or (fn.get("name") if isinstance(fn, dict) else "")
                or "unknown"
            )
            result = record.get("result")
            if result is None:
                result = record.get("output")
        else:
            tool = str(
                getattr(record, "tool_name", None)
                or getattr(record, "name", None)
                or "unknown"
            )
            result = getattr(record, "result", None)
        outcomes.append(classify_tool_result(tool, result))
    return tuple(outcomes)


def claims_completion(answer: str) -> bool:
    """True when the answer asserts the work is finished.

    Per sentence: a completion verb with no negation in the same sentence.
    "I could not update the file" is not a completion claim.
    """
    for sentence in _SENTENCE_SPLIT.split(answer or ""):
        body = sentence.strip().lower()
        if not body:
            continue
        if _COMPLETION_PATTERN.search(body) and not _NEGATION_PATTERN.search(
            body
        ):
            return True
    return False


_ANNOUNCE_MARKERS: tuple[str, ...] = (
    "i'll ",
    "i will ",
    "let me ",
    "let me start",
    "let me look",
    "let me check",
    "let me take a look",
    "i'll start",
    "i'll begin",
    "i'll take a look",
    "i'll look",
    "i'll check",
    "i'm going to",
    "i am going to",
    "first, i'll",
    "let's start",
    "going to start by",
    "now let me",
    "now i'll",
    "now i will",
    "now i'm going",
    "now, let me",
    "next, i'll",
    "next i'll",
    "let me now",
)

# Announcements of a follow-up the USER must trigger ("I'll push once you
# approve"). A legitimate hand-back, not a stall, so never nudge these.
_HAND_BACK_MARKERS: tuple[str, ...] = (
    "let me know",
    "once you",
    "when you",
    "if you want",
    "if you'd like",
    "your call",
    "your go",
)

# Plan/design narration: a status message about what is coming, not a report.
_PLAN_MARKERS: tuple[str, ...] = (
    "here's the plan",
    "here's my plan",
    "here's what i'm building",
    "here's what i'll build",
    "i'm building against",
    "reading this as",
    "design read",
    "before i start",
    "say go",
    "standing by",
    "ready to start",
)

# Past this length a reply is only narration when it is explicitly a plan;
# otherwise it is an answer and must never be nudged.
_MAX_ANNOUNCE_CHARS = 1200
_PLAIN_ANSWER_CHARS = 400

# Requests that are chat, not work — never nudge these even if the reply is short.
_CHATTY_MESSAGES: frozenset[str] = frozenset(
    {
        "hi",
        "hii",
        "hey",
        "hello",
        "yo",
        "how are you",
        "how are you?",
        "thanks",
        "thank you",
        "ok",
        "okay",
        "cool",
        "nice",
        "great",
    }
)

#: Corrective continuations allowed before a turn is committed anyway.
MAX_TURN_CONTINUATIONS = 2


def looks_like_announce_and_stop(content: str, question: str) -> bool:
    """True when a turn produced ONLY an intent preamble (e.g. "I'll start by
    looking at the files…") with no work delivered, on a message that asked for
    work. Used to auto-continue ONCE instead of stalling until the user
    re-prompts. Conservative on purpose: short reply + future-intent phrasing +
    a non-chatty request. An error reply (e.g. a 429 dump) won't match the
    markers, so we never nudge on errors."""
    if not content:
        return False
    c = content.strip().lower()
    if not c or len(c) > _MAX_ANNOUNCE_CHARS:
        return False
    if any(m in c for m in _HAND_BACK_MARKERS):
        return False
    has_marker = any(m in c for m in _ANNOUNCE_MARKERS)
    has_plan = any(m in c for m in _PLAN_MARKERS)
    if len(c) > _PLAIN_ANSWER_CHARS:
        if not has_plan:
            return False
    # Also catch fragmentary "about to do the next step" preambles that trail
    # off into a colon, e.g. "Now the host side:" — very short, ends with ':'.
    elif not (has_marker or has_plan or (c.endswith(":") and len(c) < 90)):
        return False
    q = (question or "").strip().lower().rstrip("!.")
    if q in _CHATTY_MESSAGES or len(q) < 3:
        return False
    return True


def should_auto_continue(
    content: str,
    question: str,
    *,
    tool_called: bool,
    answer_from_fallback: bool,
    todo_in_progress: bool = False,
) -> bool:
    """Decide whether a finished turn should be nudged to keep going.

    Two failure shapes are covered:

    * ``tool_called=False`` — the model replied with ONLY an intent preamble
      ("I'll start by looking at the files…") and ended with zero tool calls.
      This is the original announce-and-stop case.

    * ``todo_in_progress`` — the turn ended with an unfinished todo. This
      holds regardless of ``tool_called`` / ``answer_from_fallback`` and does
      not depend on how the message is phrased.

    * ``tool_called=True`` AND ``answer_from_fallback`` — the model DID run
      tools but its trailing segment (the text after the last tool call) was
      empty, so the caller resurrected the last non-empty segment, which was a
      pre-tool-call PREAMBLE. The user sees "Let me start by checking…" and the
      turn ends, even though work was done.

    * ``tool_called=True`` AND no completion claim — the model wrote its own
      closing message, but that message only promises the next step
      ("...Let me measure it properly.") and reports no result.

    Deliberately conservative: the content must still look like an intent
    preamble (short + future-intent phrasing) and the request must not be
    chit-chat, so a real answer that merely happens to start with "I'll" is
    never nudged.
    """
    body = (content or "").strip()
    if not body:
        return False
    q = (question or "").strip().lower().rstrip("!.")
    if q in _CHATTY_MESSAGES or len(q) < 3:
        return False
    # An open todo is proof the task is unfinished, however many tools ran and
    # however long the message was. This is the case the prose guard missed.
    if todo_in_progress and "?" not in body[-200:]:
        return True
    if not looks_like_announce_and_stop(body, question):
        return False
    # No tool run at all → classic announce-and-stop.
    if not tool_called:
        return True
    # Tools ran. A resurrected pre-tool preamble is always a stall. A genuine
    # trailing message stalls too when it only announces the next step and
    # reports no result ("...Let me measure it properly.").
    return answer_from_fallback or not claims_completion(body)


def _open_obligations(state: TurnEndState) -> list[str]:
    reasons: list[str] = []
    if state.todo_open:
        reasons.append("todo_open")
    last = state.last_outcome
    if (
        last is not None
        and last.is_failure
        and claims_completion(state.answer)
    ):
        reasons.append("completion_claim_unsupported")
    if state.tool_rounds == 0 and state.wants_work:
        # A turn that ends by asking the user something is a legitimate stop:
        # the model is waiting on a decision, not dodging the work.
        if "?" not in state.answer.strip()[-200:]:
            reasons.append("action_not_taken")
    if state.announce_continue:
        reasons.append("announce_and_stop")
    return reasons


def outstanding_reasons(state: TurnEndState) -> tuple[str, ...]:
    """Obligations still open, for the end-of-turn log."""
    return tuple(
        reason
        for reason in _open_obligations(state)
        if reason != "announce_and_stop"
    )


def evaluate_turn_end(
    state: TurnEndState, attempt: int = 0
) -> TurnEndDecision:
    """Decide whether this turn may be committed as finished.

    Obligations are checked in priority order. ``attempt`` is the number of
    corrective continuations already sent, so a later attempt asks for a report
    instead of repeating the same correction.
    """
    reasons = _open_obligations(state)
    if not reasons:
        return TurnEndDecision(continue_turn=False, reason="")

    if attempt > 0:
        return TurnEndDecision(
            continue_turn=True, reason=reasons[0], nudge=_NUDGE_REPORT
        )

    if "todo_open" in reasons:
        nudge = _NUDGE_TODO
    elif "completion_claim_unsupported" in reasons:
        nudge = _NUDGE_COMPLETION
    elif "action_not_taken" in reasons:
        nudge = _NUDGE_ACTION
    else:
        nudge = _NUDGE_ANNOUNCE
    return TurnEndDecision(continue_turn=True, reason=reasons[0], nudge=nudge)
