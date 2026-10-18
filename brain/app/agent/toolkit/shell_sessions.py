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

"""Project-scoped shell session registry shared across toolkit instances.

The brain builds a fresh ``TerminalToolkit`` per turn, so an instance-owned
dict cannot see a server started in an earlier turn. This module keeps the
session records keyed by project path instead, and owns process-group
termination so killing a shell also kills the children it spawned.
"""

from __future__ import annotations

import logging
import os
import re
import signal
import socket
import subprocess
import threading
import time

logger = logging.getLogger("shell_sessions")

_REGISTRY: dict[str, dict[str, dict]] = {}
_LOCK = threading.RLock()

_PORT_PATTERNS = (
    re.compile(r"--port[= ](\d{1,5})\b"),
    re.compile(r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(\d{2,5})\b"),
    re.compile(r"\bhttp\.server\s+(\d{2,5})\b"),
)


def project_key(working_dir: str | None) -> str:
    """Stable key for a workspace, so two toolkits agree on the same project."""
    return os.path.realpath(working_dir or os.getcwd())


def register(project: str, session: dict) -> None:
    with _LOCK:
        sessions = _REGISTRY.setdefault(project, {})
        sessions[session["id"]] = session
        # dead records only cost memory; drop them when a new one arrives
        for session_id, known in list(sessions.items()):
            if session_id != session["id"] and not is_running(known):
                sessions.pop(session_id, None)


def get(project: str, session_id: str) -> dict | None:
    with _LOCK:
        return _REGISTRY.get(project, {}).get(session_id)


def find(project: str, session_id: str) -> dict | None:
    """Resolve a session in this project first, then anywhere.

    The fallback keeps ``shell_kill_process`` working when a later turn runs
    with a different working directory but the same server id.
    """
    with _LOCK:
        session = _REGISTRY.get(project, {}).get(session_id)
        if session is not None:
            return session
        for sessions in _REGISTRY.values():
            if session_id in sessions:
                return sessions[session_id]
    return None


def forget(project: str, session_id: str) -> None:
    with _LOCK:
        _REGISTRY.get(project, {}).pop(session_id, None)


def is_running(session: dict) -> bool:
    process = session.get("process")
    if process is not None and process.poll() is None:
        return True
    pgid = session.get("pgid")
    if os.name != "nt" and pgid is not None and _group_alive(pgid):
        # the shell exited but a background child still holds the group
        return True
    return False


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def terminate_tree(session: dict, grace: float = 2.0) -> str:
    """Stop the shell and every child it spawned.

    Returns one of ``terminated``, ``already exited`` or ``no process`` so the
    caller can report what actually happened. A shell that already exited can
    still leave a background child in its process group, so the stored pgid is
    killed even when the direct process is gone.
    """
    process = session.get("process")
    pgid = session.get("pgid")
    if pgid is None and process is not None:
        try:
            pgid = os.getpgid(process.pid)
        except ProcessLookupError:
            pgid = None

    if process is None:
        if pgid is not None and _group_alive(pgid):
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            session["running"] = False
            return "terminated"
        session["running"] = False
        return "no process"

    if process.poll() is not None:
        if pgid is None or not _group_alive(pgid):
            session["running"] = False
            return "already exited"
        # the shell is gone but a background child still holds the group
        try:
            os.killpg(pgid, signal.SIGTERM)
            time.sleep(0.2)
            if _group_alive(pgid):
                os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        session["running"] = False
        return "terminated"

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            process.kill()
        session["running"] = False
        return "terminated"

    try:
        if pgid is not None:
            os.killpg(pgid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        session["running"] = False
        return "already exited"

    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        try:
            if pgid is not None:
                os.killpg(pgid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            logger.warning(
                "Session %s did not exit after SIGKILL", session.get("id")
            )

    # the leader can exit while a child ignores SIGTERM and stays in the group
    if pgid is not None and _group_alive(pgid):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    session["running"] = False
    return "terminated"


def ports_in_command(command: str) -> list[int]:
    ports: list[int] = []
    for pattern in _PORT_PATTERNS:
        for match in pattern.finditer(command or ""):
            port = int(match.group(1))
            if 1 <= port <= 65535 and port not in ports:
                ports.append(port)
    return ports


def port_is_open(port: int, timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_ports_closed(ports: list[int], timeout: float = 1.0) -> list[int]:
    deadline = time.time() + timeout
    remaining = list(ports)
    while remaining and time.time() < deadline:
        remaining = [port for port in remaining if port_is_open(port)]
        if remaining:
            time.sleep(0.05)
    return remaining
