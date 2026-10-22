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

from types import SimpleNamespace

from app.service.turn_end_guard import (
    ToolOutcome,
    TurnEndState,
    claims_completion,
    classify_tool_records,
    classify_tool_result,
    evaluate_turn_end,
    looks_like_action_request,
    outstanding_reasons,
    should_auto_continue,
)


class TestLooksLikeActionRequest:
    def test_imperative_is_a_work_request(self) -> None:
        assert looks_like_action_request("commit what we have")

    def test_imperative_mid_message_beats_a_trailing_question(self) -> None:
        assert looks_like_action_request(
            "okay. commit what we have. developer agent is the workforce mode right?"
        )

    def test_polite_request_is_a_work_request(self) -> None:
        assert looks_like_action_request("can you fix the failing test?")
        assert looks_like_action_request("please update the docs")

    def test_pure_question_is_not_a_work_request(self) -> None:
        assert not looks_like_action_request("how do I fix this?")
        assert not looks_like_action_request("can it be fixed?")
        assert not looks_like_action_request(
            "what do you think about this file?"
        )

    def test_chat_and_empty_are_not_work_requests(self) -> None:
        assert not looks_like_action_request("thanks!")
        assert not looks_like_action_request("ok, sounds good")
        assert not looks_like_action_request("")
        assert not looks_like_action_request("   ")

    def test_go_ahead_is_a_work_request(self) -> None:
        assert looks_like_action_request("yes, go ahead")


class TestClassifyToolResult:
    def test_governance_denial_is_blocked(self) -> None:
        outcome = classify_tool_result(
            "file_edit",
            "[SYSTEM GOVERNANCE]: the requested 'file_edit' action was denied "
            "by a human.",
        )
        assert outcome.blocked and outcome.is_failure

    def test_error_prefixed_result_failed(self) -> None:
        assert classify_tool_result(
            "shell_exec", "Error: command not found"
        ).failed
        assert classify_tool_result(
            "shell_exec", "Traceback (most recent call last):\n  ..."
        ).failed

    def test_error_inside_content_is_not_a_failure(self) -> None:
        # A grep hit that merely mentions 'error' is a successful tool call.
        result = "src/app.py:41: raise RuntimeError('error')"
        outcome = classify_tool_result("grep_search", result)
        assert not outcome.failed and not outcome.blocked

    def test_structured_failures(self) -> None:
        assert classify_tool_result("t", {"success": False}).failed
        assert classify_tool_result("t", {"error": "boom"}).failed
        assert classify_tool_result("t", {"blocked": True}).blocked
        assert not classify_tool_result("t", {"success": True}).is_failure

    def test_none_result_is_not_a_failure(self) -> None:
        assert not classify_tool_result("t", None).is_failure


class TestClassifyToolRecords:
    def test_objects_and_dicts(self) -> None:
        records = [
            SimpleNamespace(tool_name="read_file", result="ok"),
            {
                "tool_name": "file_edit",
                "result": "[SYSTEM GOVERNANCE]: denied",
            },
            {"function": {"name": "shell_exec"}, "result": "Exit code: 1"},
        ]
        outcomes = classify_tool_records(records)
        assert [o.tool for o in outcomes] == [
            "read_file",
            "file_edit",
            "shell_exec",
        ]
        assert outcomes[0].is_failure is False
        assert outcomes[1].is_failure is True

    def test_empty(self) -> None:
        assert classify_tool_records(None) == ()
        assert classify_tool_records([]) == ()


class TestClaimsCompletion:
    def test_positive_claims(self) -> None:
        assert claims_completion("Done. Tests pass and the fix is committed.")
        assert claims_completion("I updated the parser and removed the guard.")

    def test_negated_claims_are_not_claims(self) -> None:
        assert not claims_completion("I could not update the file.")
        assert not claims_completion(
            "Nothing updated yet; the write was blocked."
        )
        assert not claims_completion("The task is pending.")

    def test_plain_report_is_not_a_claim(self) -> None:
        assert not claims_completion("Here is what I found in the repo.")


class TestEvaluateTurnEnd:
    def _state(self, **kw):
        base = {
            "question": "commit what we have",
            "answer": "Here is what I found.",
            "tool_rounds": 1,
            "todo_open": False,
            "announce_continue": False,
            "outcomes": (),
        }
        base.update(kw)
        return TurnEndState(**base)

    def test_clean_turn_is_accepted(self) -> None:
        decision = evaluate_turn_end(self._state())
        assert not decision.continue_turn
        assert decision.reason == ""

    def test_open_todo_forces_continuation(self) -> None:
        decision = evaluate_turn_end(self._state(todo_open=True))
        assert decision.continue_turn
        assert decision.reason == "todo_open"
        assert "unfinished item" in decision.nudge

    def test_action_request_with_zero_tools_forces_continuation(self) -> None:
        decision = evaluate_turn_end(self._state(tool_rounds=0))
        assert decision.continue_turn
        assert decision.reason == "action_not_taken"
        assert "without calling a single tool" in decision.nudge

    def test_action_request_that_asks_back_is_accepted(self) -> None:
        decision = evaluate_turn_end(
            self._state(
                tool_rounds=0,
                answer="Which branch should I commit to?",
            )
        )
        assert not decision.continue_turn

    def test_conversational_question_is_accepted(self) -> None:
        decision = evaluate_turn_end(
            self._state(
                question="what does the coverage tool do?",
                answer="It measures changed-line coverage.",
                tool_rounds=0,
            )
        )
        assert not decision.continue_turn

    def test_completion_claim_after_failed_tool_forces_continuation(
        self,
    ) -> None:
        decision = evaluate_turn_end(
            self._state(
                answer="Done, the fix is committed.",
                outcomes=(ToolOutcome(tool="shell_exec", failed=True),),
            )
        )
        assert decision.continue_turn
        assert decision.reason == "completion_claim_unsupported"
        assert "Do not claim completion" in decision.nudge

    def test_failure_without_a_claim_is_accepted(self) -> None:
        decision = evaluate_turn_end(
            self._state(
                answer="The push failed; here is the error.",
                outcomes=(ToolOutcome(tool="shell_exec", failed=True),),
            )
        )
        assert not decision.continue_turn

    def test_preamble_signal_still_caught(self) -> None:
        decision = evaluate_turn_end(self._state(announce_continue=True))
        assert decision.continue_turn
        assert decision.reason == "announce_and_stop"

    def test_later_attempt_asks_for_a_report(self) -> None:
        decision = evaluate_turn_end(self._state(todo_open=True), attempt=1)
        assert decision.continue_turn
        assert "Report now" in decision.nudge

    def test_outstanding_reasons_excludes_the_preamble_signal(self) -> None:
        state = self._state(announce_continue=True, todo_open=True)
        assert outstanding_reasons(state) == ("todo_open",)
        assert outstanding_reasons(self._state()) == ()

    def test_explicit_non_work_request_skips_the_zero_tool_rule(self) -> None:
        # A workforce worker's prompt is a structured task, not the user's
        # message, so it opts out of the "no tool ran" rule.
        decision = evaluate_turn_end(
            self._state(
                tool_rounds=0,
                answer="Here is the design.",
                action_request=False,
            )
        )
        assert not decision.continue_turn


class TestShouldAutoContinue:
    def test_no_tool_run_and_a_preamble_nudges(self) -> None:
        assert should_auto_continue(
            "Let me measure it properly.",
            "measure the dish on a phone",
            tool_called=False,
            answer_from_fallback=False,
        )

    def test_real_report_after_tools_is_accepted(self) -> None:
        assert not should_auto_continue(
            "Added the guard and 3 tests; all 40 pass.",
            "add the guard to workforce",
            tool_called=True,
            answer_from_fallback=False,
        )

    def test_resurrected_preamble_after_tools_nudges(self) -> None:
        assert should_auto_continue(
            "Let me read the file.",
            "fix the bug",
            tool_called=True,
            answer_from_fallback=True,
        )

    def test_closing_preamble_without_a_result_nudges(self) -> None:
        assert should_auto_continue(
            "I pulled both components apart rather than guessing. Let me "
            "measure it properly.",
            "compare the two versions",
            tool_called=True,
            answer_from_fallback=False,
        )

    def test_hand_back_is_accepted(self) -> None:
        assert not should_auto_continue(
            "Let me know if you want me to push.",
            "fix the bug",
            tool_called=True,
            answer_from_fallback=False,
        )

    def test_chat_is_never_nudged(self) -> None:
        assert not should_auto_continue(
            "Let me check.",
            "thanks",
            tool_called=False,
            answer_from_fallback=False,
        )

    def test_open_todo_nudges_regardless_of_wording(self) -> None:
        assert should_auto_continue(
            "Coverage is measured per changed line.",
            "measure coverage",
            tool_called=True,
            answer_from_fallback=False,
            todo_in_progress=True,
        )
