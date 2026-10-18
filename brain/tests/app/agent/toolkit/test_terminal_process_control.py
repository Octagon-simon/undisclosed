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

import asyncio
import socket
import sys
import time
import uuid

import pytest

from app.agent.toolkit import shell_sessions
from app.agent.toolkit.terminal_toolkit import TerminalToolkit
from app.service.task import TaskLock, task_locks


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.05)
    return False


def _make_toolkit(working_directory) -> tuple[TerminalToolkit, str]:
    api_task_id = f"test_terminal_{uuid.uuid4().hex[:8]}"
    task_locks[api_task_id] = TaskLock(
        id=api_task_id, queue=asyncio.Queue(), human_input={}
    )
    return (
        TerminalToolkit(api_task_id, working_directory=str(working_directory)),
        api_task_id,
    )


@pytest.mark.unit
class TestTerminalProcessControl:
    def teardown_method(self):
        for task_id in list(task_locks):
            if task_id.startswith("test_terminal_"):
                task_locks.pop(task_id, None)

    def test_background_child_does_not_block_completion(self, tmp_path):
        toolkit, _ = _make_toolkit(tmp_path)
        started = time.monotonic()
        output = toolkit.shell_exec(
            "sleep 30 & echo started", id="not-blocked"
        )
        elapsed = time.monotonic() - started

        try:
            assert "started" in output
            assert elapsed < 5.0, f"blocking call waited {elapsed:.1f}s"
        finally:
            toolkit.shell_kill_process("not-blocked")

    def test_timeout_converts_to_killable_session(self, tmp_path):
        toolkit, _ = _make_toolkit(tmp_path)
        port = _free_port()
        started = time.monotonic()
        output = toolkit.shell_exec(
            f"{sys.executable} -m http.server {port}", id="slow", timeout=0.5
        )
        elapsed = time.monotonic() - started

        try:
            assert "still running after 0.5s" in output
            assert elapsed < 5.0, f"timeout took {elapsed:.1f}s"
            assert _wait_for_port(port)
        finally:
            result = toolkit.shell_kill_process("slow")

        assert "terminated" in result.lower()
        time.sleep(0.2)
        assert not shell_sessions.port_is_open(port)

    def test_background_server_output_and_port_release(self, tmp_path):
        toolkit, _ = _make_toolkit(tmp_path)
        port = _free_port()
        toolkit.shell_exec(
            f"{sys.executable} -m http.server {port}", id="server", block=False
        )
        try:
            assert _wait_for_port(port)
            deadline = time.monotonic() + 3.0
            seen = ""
            while time.monotonic() < deadline and "Serving HTTP" not in seen:
                seen += toolkit.shell_view("server")
                time.sleep(0.1)
            assert "Serving HTTP" in seen
        finally:
            result = toolkit.shell_kill_process("server")

        assert "port" in result.lower()
        time.sleep(0.2)
        assert not shell_sessions.port_is_open(port)

    def test_session_survives_into_a_second_toolkit(self, tmp_path):
        first, api_task_id = _make_toolkit(tmp_path)
        first.shell_exec("sleep 30", id="cross-turn", block=False)
        second = TerminalToolkit(api_task_id, working_directory=str(tmp_path))

        try:
            view = second.shell_view("cross-turn")
            assert "No session found" not in view
            result = second.shell_kill_process("cross-turn")
            assert "terminated" in result.lower()
        finally:
            first.shell_kill_process("cross-turn")
            shell_sessions.forget(str(tmp_path.resolve()), "cross-turn")

    def test_kill_stops_orphaned_process_group(self, tmp_path):
        toolkit, _ = _make_toolkit(tmp_path)
        toolkit.shell_exec("sleep 30 & echo started", id="orphan")

        result = toolkit.shell_kill_process("orphan")
        assert "terminated" in result.lower()

    def test_empty_output_is_reported_as_success(self, tmp_path):
        toolkit, _ = _make_toolkit(tmp_path)
        assert "executed successfully" in toolkit.shell_exec(
            "true", id="empty"
        )

    def test_stderr_is_captured(self, tmp_path):
        toolkit, _ = _make_toolkit(tmp_path)
        assert "boom" in toolkit.shell_exec("echo boom >&2", id="stderr")

    def test_blocked_command_is_rejected_before_spawn(self, tmp_path):
        toolkit, _ = _make_toolkit(tmp_path)
        output = toolkit.shell_exec("rm -rf missing-dir", id="blocked")
        assert "blocked by the command policy" in output
        assert shell_sessions.find(str(tmp_path.resolve()), "blocked") is None

    def test_read_only_command_runs_without_a_gate(self, tmp_path):
        toolkit, _ = _make_toolkit(tmp_path)
        assert "hello" in toolkit.shell_exec("echo hello", id="read-only")

    def test_workspace_write_still_runs_while_ungated(self, tmp_path):
        toolkit, _ = _make_toolkit(tmp_path)
        toolkit.shell_exec("mkdir made", id="write")
        assert (tmp_path / "made").is_dir()
