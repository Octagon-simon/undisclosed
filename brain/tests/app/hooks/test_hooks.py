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

import asyncio
import json
import time

import pytest

from app.hooks.config import parse_hooks_env, resolve_commands_for_event
from app.hooks.dispatcher import (
    DEFAULT_HOOK_TIMEOUT_SECONDS,
    dispatch_payload,
    fire_hook,
    get_hook_timeout,
    run_hook_command,
)
from app.hooks.emitters import (
    emit_permission_requested,
    emit_permission_resolved,
    emit_task_completed,
)
from app.hooks.events import HookEvent, build_payload
from app.utils.notify import NOTIFY_TIMEOUT_SECONDS, fire_notify

# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


class TestParseHooksEnv:
    def test_unset_returns_empty(self, monkeypatch):
        monkeypatch.delenv("EIGENT_HOOKS", raising=False)
        assert parse_hooks_env(None) == {}
        assert parse_hooks_env("") == {}

    def test_invalid_json_returns_empty(self, monkeypatch):
        monkeypatch.setenv("EIGENT_HOOKS", "{not json")
        assert parse_hooks_env("{not json") == {}

    def test_non_dict_returns_empty(self, monkeypatch):
        assert parse_hooks_env('["a", "b"]') == {}

    def test_unknown_event_key_ignored(self):
        table = parse_hooks_env(json.dumps({"not_an_event": "cmd"}))
        assert table == {}

    def test_string_value_becomes_single_entry(self):
        table = parse_hooks_env(
            json.dumps({"permission_requested": "node hook.js"})
        )
        assert table == {"permission_requested": ["node hook.js"]}

    def test_list_value_normalized(self):
        table = parse_hooks_env(
            json.dumps({"*": ["cmd_a", "cmd_b"], "task_end": "cmd_c"})
        )
        assert table["*"] == ["cmd_a", "cmd_b"]
        assert table["task_end"] == ["cmd_c"]

    def test_explicit_empty_list_preserved(self):
        table = parse_hooks_env(json.dumps({"task_end": []}))
        # Empty list means "suppress hooks for this event"; parser must keep
        # the key so resolution knows not to fall back.
        assert table == {"task_end": []}


# ---------------------------------------------------------------------------
# Resolution precedence
# ---------------------------------------------------------------------------


class TestResolution:
    def test_nothing_configured_is_noop(self, monkeypatch):
        monkeypatch.delenv("EIGENT_HOOKS", raising=False)
        monkeypatch.delenv("EIGENT_NOTIFY_COMMAND", raising=False)
        assert resolve_commands_for_event(HookEvent.task_end) == []

    def test_legacy_command_fires_for_every_event(self, monkeypatch):
        monkeypatch.delenv("EIGENT_HOOKS", raising=False)
        monkeypatch.setenv(
            "EIGENT_NOTIFY_COMMAND", "node beckoned-eigent-hook.js"
        )
        assert resolve_commands_for_event(HookEvent.task_end) == [
            "node beckoned-eigent-hook.js"
        ]
        assert resolve_commands_for_event(HookEvent.permission_requested) == [
            "node beckoned-eigent-hook.js"
        ]

    def test_specific_adds_to_legacy(self, monkeypatch):
        """Adding a routed command must not silently unhook existing setups."""
        monkeypatch.setenv(
            "EIGENT_HOOKS",
            json.dumps({"task_end": "specific.sh"}),
        )
        monkeypatch.setenv("EIGENT_NOTIFY_COMMAND", "legacy.sh")
        assert resolve_commands_for_event(HookEvent.task_end) == [
            "specific.sh",
            "legacy.sh",
        ]
        # Events without their own entry keep firing the legacy command.
        assert resolve_commands_for_event(HookEvent.task_failed) == [
            "legacy.sh"
        ]

    def test_duplicate_command_deduplicated(self, monkeypatch):
        monkeypatch.setenv("EIGENT_HOOKS", json.dumps({"*": "same.sh"}))
        monkeypatch.setenv("EIGENT_NOTIFY_COMMAND", "same.sh")
        assert resolve_commands_for_event(HookEvent.task_end) == ["same.sh"]

    def test_wildcard_combines_with_legacy(self, monkeypatch):
        monkeypatch.setenv("EIGENT_HOOKS", json.dumps({"*": "audit.sh"}))
        monkeypatch.setenv("EIGENT_NOTIFY_COMMAND", "legacy.sh")
        resolved = resolve_commands_for_event(HookEvent.task_started)
        assert resolved == ["audit.sh", "legacy.sh"]

    def test_explicit_empty_list_suppresses_fallbacks(self, monkeypatch):
        monkeypatch.setenv("EIGENT_HOOKS", json.dumps({"task_end": []}))
        monkeypatch.setenv("EIGENT_NOTIFY_COMMAND", "legacy.sh")
        assert resolve_commands_for_event(HookEvent.task_end) == []
        assert resolve_commands_for_event(HookEvent.task_started) == [
            "legacy.sh"
        ]

    def test_accepts_plain_string_event_names(self, monkeypatch):
        monkeypatch.delenv("EIGENT_HOOKS", raising=False)
        monkeypatch.setenv("EIGENT_NOTIFY_COMMAND", "legacy.sh")
        # Callers may pass raw strings (back-compat with fire_notify).
        assert resolve_commands_for_event("human_input_requested") == [
            "legacy.sh"
        ]


# ---------------------------------------------------------------------------
# Payload building
# ---------------------------------------------------------------------------


class TestPayload:
    def test_shape_and_types(self):
        payload = build_payload(
            HookEvent.permission_requested, {"taskId": "t1"}
        )
        assert payload["event"] == "permission_requested"
        assert payload["taskId"] == "t1"
        assert isinstance(payload["timestamp"], float)

    def test_flat_scalars_only(self):
        payload = build_payload(HookEvent.task_end, {"taskId": "t1"})
        assert all(isinstance(v, (str, int, float)) for v in payload.values())

    def test_data_collision_on_event_key_is_canonical(self):
        payload = build_payload(HookEvent.task_end, {"event": "evil"})
        assert payload["event"] == "task_end"


# ---------------------------------------------------------------------------
# Dispatcher (real subprocesses)
# ---------------------------------------------------------------------------

CAPTURE_CMD = "cat > {out}"


def capture_cmd(out_path) -> str:
    return CAPTURE_CMD.format(out=str(out_path))


def read_capture(out_path) -> dict:
    raw = out_path.read_text()
    assert raw.strip(), "hook command received empty stdin"
    return json.loads(raw)


class TestRunHookCommand:
    @pytest.mark.asyncio
    async def test_payload_reaches_stdin(self, tmp_path):
        out = tmp_path / "captured.json"
        await run_hook_command(capture_cmd(out), {"event": "task_end"})
        payload = read_capture(out)
        assert payload["event"] == "task_end"

    @pytest.mark.asyncio
    async def test_missing_binary_does_not_raise(self):
        await run_hook_command(
            "/nonexistent/binary/for/hooks/test", {"event": "x"}
        )

    @pytest.mark.asyncio
    async def test_failing_command_does_not_raise(self):
        await run_hook_command("false", {"event": "x"})

    @pytest.mark.asyncio
    async def test_stderr_output_swallowed(self):
        await run_hook_command("echo oops >&2; exit 3", {"event": "x"})

    @pytest.mark.asyncio
    async def test_timeout_kills_process(self, monkeypatch, tmp_path):
        marker = tmp_path / "never"
        monkeypatch.setenv("EIGENT_HOOK_TIMEOUT_MS", "150")
        start = time.monotonic()
        await run_hook_command(f"sleep 30; touch {marker}", {"event": "x"})
        elapsed = time.monotonic() - start
        assert elapsed < 5, "hook must be killed shortly after the timeout"
        assert not marker.exists()
        # Sanity: default override parsed.
        assert get_hook_timeout() == pytest.approx(0.15)

    def test_default_timeout(self, monkeypatch):
        monkeypatch.delenv("EIGENT_HOOK_TIMEOUT_MS", raising=False)
        assert get_hook_timeout() == DEFAULT_HOOK_TIMEOUT_SECONDS
        assert DEFAULT_HOOK_TIMEOUT_SECONDS == NOTIFY_TIMEOUT_SECONDS

    @pytest.mark.asyncio
    async def test_invalid_timeout_falls_back(self, monkeypatch):
        monkeypatch.setenv("EIGENT_HOOK_TIMEOUT_MS", "abc")
        assert get_hook_timeout() == DEFAULT_HOOK_TIMEOUT_SECONDS


class TestFanOut:
    @pytest.mark.asyncio
    async def test_all_commands_receive_payload(self, tmp_path):
        outs = [tmp_path / f"out{i}.json" for i in range(3)]
        await dispatch_payload(
            [capture_cmd(o) for o in outs], {"event": "task_started"}
        )
        for out in outs:
            assert read_capture(out)["event"] == "task_started"

    @pytest.mark.asyncio
    async def test_one_bad_command_does_not_block_others(self, tmp_path):
        good = tmp_path / "good.json"
        await dispatch_payload(
            ["/nonexistent/binary", capture_cmd(good)], {"event": "x"}
        )
        assert read_capture(good)["event"] == "x"


class TestFireHook:
    @pytest.mark.asyncio
    async def test_noop_when_unconfigured(self, monkeypatch):
        monkeypatch.delenv("EIGENT_HOOKS", raising=False)
        monkeypatch.delenv("EIGENT_NOTIFY_COMMAND", raising=False)
        # Must return promptly without spawning anything.
        await asyncio.wait_for(
            fire_hook(HookEvent.task_end, taskId="t1"), timeout=2
        )

    @pytest.mark.asyncio
    async def test_routes_via_config(self, monkeypatch, tmp_path):
        out = tmp_path / "routed.json"
        monkeypatch.setenv(
            "EIGENT_HOOKS",
            json.dumps({"permission_requested": capture_cmd(out)}),
        )
        monkeypatch.delenv("EIGENT_NOTIFY_COMMAND", raising=False)
        await fire_hook(
            HookEvent.permission_requested,
            taskId="t1",
            actionId="a1",
            toolName="TerminalToolkit.run_command",
            category="shell",
            description="npm test",
            agentName="single_agent",
        )
        payload = read_capture(out)
        assert payload["event"] == "permission_requested"
        assert payload["toolName"] == "TerminalToolkit.run_command"
        assert payload["category"] == "shell"

    @pytest.mark.asyncio
    async def test_never_raises_even_if_resolution_explodes(self, monkeypatch):
        monkeypatch.setattr(
            "app.hooks.dispatcher.resolve_commands_for_event",
            lambda event: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        await fire_hook(HookEvent.task_end)


# ---------------------------------------------------------------------------
# Semantic emitters
# ---------------------------------------------------------------------------


class TestEmitters:
    @pytest.mark.asyncio
    async def test_permission_requested_fields(self, monkeypatch, tmp_path):
        out = tmp_path / "perm.json"
        monkeypatch.setenv(
            "EIGENT_HOOKS",
            json.dumps({"permission_requested": capture_cmd(out)}),
        )
        await emit_permission_requested(
            task_id="t1",
            tool_name="FileWriteToolkit.write_file",
            category="file_write",
            action_id="act-42",
            description="x" * 500,
            timeout_seconds=120.0,
        )
        payload = read_capture(out)
        assert payload["actionId"] == "act-42"
        assert payload["category"] == "file_write"
        assert len(payload["description"]) == 200  # truncated
        assert payload["timeoutSeconds"] == 120

    @pytest.mark.asyncio
    async def test_permission_resolution_events(self, monkeypatch, tmp_path):
        approved = tmp_path / "approved.json"
        denied = tmp_path / "denied.json"
        monkeypatch.setenv(
            "EIGENT_HOOKS",
            json.dumps(
                {
                    "permission_approved": capture_cmd(approved),
                    "permission_denied": capture_cmd(denied),
                }
            ),
        )
        await emit_permission_resolved(
            HookEvent.permission_approved,
            task_id="t1",
            action_id="a1",
            tool_name="run_command",
            category="shell",
        )
        await emit_permission_resolved(
            HookEvent.permission_denied,
            task_id="t1",
            action_id="a1",
            tool_name="run_command",
            category="shell",
            reason="Do not delete this file",
        )
        assert read_capture(approved)["event"] == "permission_approved"
        denied_payload = read_capture(denied)
        assert denied_payload["reason"] == "Do not delete this file"

    @pytest.mark.asyncio
    async def test_resolution_rejects_wrong_event(self):
        with pytest.raises(ValueError):
            await emit_permission_resolved(
                HookEvent.task_end,
                task_id="t1",
                action_id="a1",
                tool_name="x",
                category="shell",
            )

    @pytest.mark.asyncio
    async def test_task_completed_emits_beckon_known_task_end(
        self, monkeypatch, tmp_path
    ):
        out = tmp_path / "end.json"
        monkeypatch.setenv("EIGENT_HOOKS", json.dumps({"*": capture_cmd(out)}))
        await emit_task_completed(task_id="t9")
        payload = read_capture(out)
        assert payload["event"] == "task_end"
        assert payload["taskId"] == "t9"


# ---------------------------------------------------------------------------
# Backward compatibility (fire_notify contract)
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    @pytest.mark.asyncio
    async def test_fire_notify_with_legacy_env_only(
        self, monkeypatch, tmp_path
    ):
        """The exact setup documented in beckon's README keeps working."""
        out = tmp_path / "legacy.json"
        monkeypatch.delenv("EIGENT_HOOKS", raising=False)
        monkeypatch.setenv("EIGENT_NOTIFY_COMMAND", capture_cmd(out))
        await fire_notify(
            "human_input_requested",
            {
                "taskId": "t1",
                "agentName": "single_agent",
                "question": "Proceed?",
            },
        )
        payload = read_capture(out)
        assert payload["event"] == "human_input_requested"
        assert payload["taskId"] == "t1"
        assert payload["question"] == "Proceed?"
        assert isinstance(payload["timestamp"], float)

    @pytest.mark.asyncio
    async def test_fire_notify_unconfigured_is_silent_noop(self, monkeypatch):
        monkeypatch.delenv("EIGENT_HOOKS", raising=False)
        monkeypatch.delenv("EIGENT_NOTIFY_COMMAND", raising=False)
        await asyncio.wait_for(
            fire_notify("task_end", {"taskId": "t1"}), timeout=2
        )


# ---------------------------------------------------------------------------
# Thread-safe scheduling helper
# ---------------------------------------------------------------------------


class TestThreadSafeEmit:
    def test_emit_event_thread_safe_from_running_loop(
        self, monkeypatch, tmp_path
    ):
        from app.hooks.dispatcher import emit_event_thread_safe
        from app.utils.event_loop_utils import set_main_event_loop

        out = tmp_path / "threadsafe.json"
        monkeypatch.setenv("EIGENT_HOOKS", json.dumps({"*": capture_cmd(out)}))

        async def scenario():
            set_main_event_loop(asyncio.get_running_loop())
            # Simulate a worker thread scheduling without a running loop of
            # its own: the coroutine must land on the registered main loop.
            emit_event_thread_safe(HookEvent.task_started, taskId="ts-1")
            await asyncio.sleep(0.5)
            payload = read_capture(out)
            assert payload["event"] == "task_started"

        asyncio.run(scenario())
