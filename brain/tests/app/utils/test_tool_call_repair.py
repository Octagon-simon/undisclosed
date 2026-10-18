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

from app.utils.tool_call_repair import repair_tool_call_pairing


def _call(call_id: str, name: str = "shell_exec") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": "{}"},
    }


def _reply(call_id: str, content: str = "ok") -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def test_paired_history_is_untouched() -> None:
    messages = [
        {"role": "user", "content": "list files"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [_call("a")],
        },
        _reply("a"),
        {"role": "assistant", "content": "done"},
    ]
    before = [dict(message) for message in messages]

    assert repair_tool_call_pairing(messages) == 0
    assert messages == before


def test_orphaned_tool_call_is_dropped() -> None:
    messages = [
        {"role": "user", "content": "list files"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [_call("a")],
        },
        {"role": "user", "content": "continue"},
    ]

    removed = repair_tool_call_pairing(messages)

    assert removed == 2
    assert messages == [
        {"role": "user", "content": "list files"},
        {"role": "user", "content": "continue"},
    ]


def test_assistant_text_survives_losing_its_tool_call() -> None:
    messages = [
        {
            "role": "assistant",
            "content": "Running it now",
            "tool_calls": [_call("a")],
        },
        {"role": "user", "content": "go on"},
    ]

    repair_tool_call_pairing(messages)

    assert messages[0] == {"role": "assistant", "content": "Running it now"}


def test_partial_answers_keep_only_answered_calls() -> None:
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [_call("a"), _call("b")],
        },
        _reply("a"),
        {"role": "user", "content": "next"},
    ]

    repair_tool_call_pairing(messages)

    assert messages[0]["tool_calls"] == [_call("a")]
    assert messages[1] == _reply("a")
    assert messages[2] == {"role": "user", "content": "next"}


def test_reply_interrupted_by_another_role_is_dropped() -> None:
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [_call("a")],
        },
        {"role": "user", "content": "wait"},
        _reply("a"),
    ]

    repair_tool_call_pairing(messages)

    assert messages == [{"role": "user", "content": "wait"}]


def test_stray_tool_reply_is_dropped() -> None:
    messages = [
        {"role": "user", "content": "hi"},
        _reply("ghost"),
        {"role": "assistant", "content": "hello"},
    ]

    assert repair_tool_call_pairing(messages) == 1
    assert [message["role"] for message in messages] == ["user", "assistant"]


def test_duplicate_replies_collapse_to_one() -> None:
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [_call("a")],
        },
        _reply("a", "first"),
        _reply("a", "second"),
    ]

    repair_tool_call_pairing(messages)

    assert messages[1] == _reply("a", "first")
    assert len(messages) == 2


def test_non_list_input_is_ignored() -> None:
    assert repair_tool_call_pairing(None) == 0
    assert repair_tool_call_pairing("nope") == 0
    assert repair_tool_call_pairing([]) == 0
