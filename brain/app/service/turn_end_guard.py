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
"""Turn-end validation for the single agent.

The question a turn answers is not "did the model stop talking?" but "is any
execution still owed?" This module derives that from runtime state: open todos,
tool rounds, tool results, and whether the request asked for work at all. The
legacy preamble detector is passed in as one signal instead of being the rule.

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
    if state.tool_rounds == 0 and looks_like_action_request(state.question):
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
