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

import asyncio
import logging
import os
import platform
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from camel.toolkits.terminal_toolkit import (
    TerminalToolkit as BaseTerminalToolkit,
)
from camel.toolkits.terminal_toolkit.terminal_toolkit import _to_plain

from app.agent.toolkit import shell_sessions
from app.agent.toolkit.abstract_toolkit import AbstractToolkit
from app.agent.toolkit.command_policy import assess_command
from app.component.environment import env
from app.service.task import (
    Action,
    ActionTerminalData,
    Agents,
    get_task_lock,
    process_task,
)
from app.utils.listen.toolkit_listen import auto_listen_toolkit

logger = logging.getLogger("terminal_toolkit")

# App version - should match electron app version
# TODO: Consider getting this from a shared config
APP_VERSION = "1.0.2"

# a blocking call is bounded by wall clock, not by inherited pipe lifetime
DEFAULT_BLOCKING_TIMEOUT = 10.0
# a command that has not finished by then is reported as a live session
STARTED_MESSAGE_TAIL = 4_000
# keep a single result from flooding the model context
MAX_RESULT_CHARS = 100_000


def get_terminal_base_venv_path() -> str:
    """Get the path to the terminal base venv created during app installation."""
    return os.path.join(
        os.path.expanduser("~"),
        ".undisclosed",
        "venvs",
        f"terminal_base-{APP_VERSION}",
    )


@auto_listen_toolkit(BaseTerminalToolkit)
class TerminalToolkit(BaseTerminalToolkit, AbstractToolkit):
    agent_name: str = Agents.developer_agent
    _thread_pool: ThreadPoolExecutor | None = None
    _thread_local = threading.local()

    def __init__(
        self,
        api_task_id: str,
        agent_name: str | None = None,
        timeout: float | None = None,
        working_directory: str | None = None,
        use_docker_backend: bool = False,
        docker_container_name: str | None = None,
        session_logs_dir: str | None = None,
        safe_mode: bool = True,
        allowed_commands: list[str] | None = None,
        clone_current_env: bool = True,
    ):
        self.api_task_id = api_task_id
        if agent_name is not None:
            self.agent_name = agent_name

        # Get base directory from environment
        base_dir = env(
            "file_save_path", os.path.expanduser("~/.undisclosed/terminal/")
        )

        if working_directory is None:
            working_directory = base_dir
        self._agent_venv_dir = os.path.join(base_dir, self.agent_name)

        logger.debug(
            f"Initializing TerminalToolkit for agent={self.agent_name}",
            extra={
                "api_task_id": api_task_id,
                "working_directory": working_directory,
                "agent_venv_dir": self._agent_venv_dir,
            },
        )

        if TerminalToolkit._thread_pool is None:
            TerminalToolkit._thread_pool = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="terminal_toolkit"
            )

        super().__init__(
            timeout=timeout,
            working_directory=working_directory,
            use_docker_backend=use_docker_backend,
            docker_container_name=docker_container_name,
            session_logs_dir=session_logs_dir,
            safe_mode=safe_mode,
            allowed_commands=allowed_commands,
            clone_current_env=True,
            install_dependencies=[],
        )

        # the base class wipes *.log directly in log_dir on every construction,
        # so session logs live one level down and survive into later turns
        self._session_log_dir = os.path.join(self.log_dir, "sessions")
        os.makedirs(self._session_log_dir, exist_ok=True)
        self._log_lock = threading.RLock()

        # Auto-register with TaskLock for cleanup when task ends
        from app.service.task import get_task_lock_if_exists

        task_lock = get_task_lock_if_exists(api_task_id)
        if task_lock:
            task_lock.register_toolkit(self)
            logger.info(
                "TerminalToolkit registered for cleanup",
                extra={
                    "api_task_id": api_task_id,
                    "working_directory": working_directory,
                },
            )

    def _setup_cloned_environment(self):
        """Override to clone from terminal_base venv instead of current process venv.

        Creates a lightweight clone using symlinks to the terminal_base venv,
        which contains pre-installed packages (pandas, numpy, matplotlib, etc.).
        """
        self.cloned_env_path = os.path.join(self._agent_venv_dir, ".venv")
        terminal_base_path = get_terminal_base_venv_path()

        # Check if terminal_base exists
        if platform.system() == "Windows":
            base_python = os.path.join(
                terminal_base_path, "Scripts", "python.exe"
            )
        else:
            base_python = os.path.join(terminal_base_path, "bin", "python")

        if not os.path.exists(base_python):
            logger.warning(
                f"Terminal base venv not found at {terminal_base_path}, "
                "falling back to system Python"
            )
            return

        # Check if cloned env already exists
        if platform.system() == "Windows":
            cloned_python = os.path.join(
                self.cloned_env_path, "Scripts", "python.exe"
            )
        else:
            cloned_python = os.path.join(self.cloned_env_path, "bin", "python")

        if os.path.exists(cloned_python):
            logger.info(
                f"Using existing cloned environment: {self.cloned_env_path}"
            )
            self.python_executable = cloned_python
            return

        logger.info(f"Cloning terminal_base venv to: {self.cloned_env_path}")

        try:
            # Create the cloned venv directory
            os.makedirs(self.cloned_env_path, exist_ok=True)

            # Clone using symlinks for efficiency
            # We need to create proper venv structure with symlinks to terminal_base
            self._clone_venv_with_symlinks(
                terminal_base_path, self.cloned_env_path
            )

            self.python_executable = cloned_python
            logger.info(
                f"Successfully cloned environment to: {self.cloned_env_path}"
            )

        except Exception as e:
            logger.error(
                f"Failed to clone terminal_base venv: {e}", exc_info=True
            )
            # Cleanup partial clone
            if os.path.exists(self.cloned_env_path):
                shutil.rmtree(self.cloned_env_path, ignore_errors=True)
            logger.warning("Falling back to system Python")

    def _get_venv_path(self):
        """Return the cloned venv path for shell activation."""
        cloned_env_path = getattr(self, "cloned_env_path", None)
        if cloned_env_path and os.path.exists(cloned_env_path):
            return cloned_env_path
        return None

    def _clone_venv_with_symlinks(self, source_venv: str, target_venv: str):
        """Clone a venv using symlinks for efficiency.

        Creates the structure needed: pyvenv.cfg, bin/python, lib symlink, and activate scripts.
        """
        is_windows = platform.system() == "Windows"

        # Read source pyvenv.cfg to get Python home
        source_cfg = os.path.join(source_venv, "pyvenv.cfg")
        python_home = None

        with open(source_cfg, encoding="utf-8") as f:
            for line in f:
                if line.startswith("home = "):
                    python_home = line.split("=", 1)[1].strip()
                    break

        if not python_home:
            raise RuntimeError(
                f"Could not determine Python home from {source_cfg}"
            )

        # Copy pyvenv.cfg (simpler than recreating)
        shutil.copy2(source_cfg, os.path.join(target_venv, "pyvenv.cfg"))

        if is_windows:
            # Windows: copy executables from source
            target_bin = os.path.join(target_venv, "Scripts")
            os.makedirs(target_bin, exist_ok=True)
            source_scripts = os.path.join(source_venv, "Scripts")
            for exe in ["python.exe", "pythonw.exe"]:
                src = os.path.join(source_scripts, exe)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(target_bin, exe))
            # Copy activate scripts (need to modify VIRTUAL_ENV path)
            for script in ["activate.bat", "activate.ps1", "deactivate.bat"]:
                src = os.path.join(source_scripts, script)
                if os.path.exists(src):
                    with open(src, encoding="utf-8") as f:
                        content = f.read()
                    content = content.replace(source_venv, target_venv)
                    dst = os.path.join(target_bin, script)
                    with open(dst, "w", encoding="utf-8") as f:
                        f.write(content)
            # Use directory junction for Lib (no admin rights needed, unlike symlink)
            source_lib = os.path.join(source_venv, "Lib")
            target_lib = os.path.join(target_venv, "Lib")
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", target_lib, source_lib],
                check=True,
                capture_output=True,
            )
        else:
            # Unix: symlink python executable and lib directory
            target_bin = os.path.join(target_venv, "bin")
            os.makedirs(target_bin, exist_ok=True)

            # Symlink python to the base Python
            python_exe = os.path.join(python_home, "python3")
            if not os.path.exists(python_exe):
                python_exe = os.path.join(python_home, "python")
            os.symlink(python_exe, os.path.join(target_bin, "python"))
            os.symlink("python", os.path.join(target_bin, "python3"))

            # Copy activate scripts (need to modify VIRTUAL_ENV path)
            source_bin = os.path.join(source_venv, "bin")
            for script in ["activate", "activate.csh", "activate.fish"]:
                src = os.path.join(source_bin, script)
                if os.path.exists(src):
                    with open(src) as f:
                        content = f.read()
                    # Replace source venv path with target venv path
                    content = content.replace(source_venv, target_venv)
                    dst = os.path.join(target_bin, script)
                    with open(dst, "w") as f:
                        f.write(content)

            # Symlink lib directory
            source_lib = os.path.join(source_venv, "lib")
            os.symlink(source_lib, os.path.join(target_venv, "lib"))

    def _write_to_log(self, log_file: str, content: str) -> None:
        r"""Write content to log file with optional ANSI stripping.

        Args:
            log_file (str): Path to the log file
            content (str): Content to write
        """
        # Convert ANSI escape sequences to plain text
        super()._write_to_log(log_file, content)
        logger.debug(
            "Terminal output logged",
            extra={
                "api_task_id": self.api_task_id,
                "log_file": log_file,
                "content_length": len(content),
            },
        )
        self._update_terminal_output(_to_plain(content))

    def _update_terminal_output(self, output: str):
        task_lock = get_task_lock(self.api_task_id)
        process_task_id = process_task.get("")

        # Create the coroutine
        coro = task_lock.put_queue(
            ActionTerminalData(
                action=Action.terminal,
                process_task_id=process_task_id,
                data=output,
            )
        )

        # Try to get the current event loop, if none exists, create a new one in a thread
        try:
            loop = asyncio.get_running_loop()
            # If we're in an async context, schedule the coroutine
            task = loop.create_task(coro)
            if hasattr(task_lock, "add_background_task"):
                task_lock.add_background_task(task)
        except RuntimeError:
            self._thread_pool.submit(self._run_coro_in_thread, coro, task_lock)

    @staticmethod
    def _run_coro_in_thread(coro, task_lock):
        """
        Execute coro in the thread pool, with each thread bound to a long-term event loop
        """
        if not hasattr(TerminalToolkit._thread_local, "loop"):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            TerminalToolkit._thread_local.loop = loop
        else:
            loop = TerminalToolkit._thread_local.loop

        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            TerminalToolkit._thread_local.loop = loop

        try:
            task = loop.create_task(coro)
            if hasattr(task_lock, "add_background_task"):
                task_lock.add_background_task(task)
            loop.run_until_complete(task)
        except Exception as e:
            logging.error(
                f"Failed to execute coroutine in thread pool: {str(e)}",
                exc_info=True,
            )

    def _project_key(self) -> str:
        return shell_sessions.project_key(self.working_dir)

    def _session_log_file(self, session_id: str) -> str:
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)
        return os.path.join(self._session_log_dir, f"{safe_id}.log")

    def _tail_text(
        self,
        log_file: str,
        limit: int = STARTED_MESSAGE_TAIL,
        strip_header: bool = False,
    ) -> str:
        try:
            size = os.path.getsize(log_file)
            with open(log_file, encoding="utf-8", errors="replace") as handle:
                if size > limit:
                    handle.seek(size - limit)
                text = handle.read()
        except OSError:
            return ""
        text = _to_plain(text)
        if strip_header:
            marker = text.find("\n$ ")
            if marker != -1:
                text = text[marker + 3 :]
                first_newline = text.find("\n")
                if first_newline != -1:
                    text = text[first_newline + 1 :]
        if size > limit:
            text = "...(truncated)...\n" + text
        return text

    def _read_result(
        self, session: dict, limit: int = MAX_RESULT_CHARS
    ) -> str:
        log_file = session.get("log_file")
        if not log_file:
            return ""
        try:
            size = os.path.getsize(log_file)
            start = session.get("offset", 0)
            with open(log_file, encoding="utf-8", errors="replace") as handle:
                if size - start > limit:
                    handle.seek(size - limit)
                    text = "...(truncated)...\n" + handle.read()
                else:
                    handle.seek(start)
                    text = handle.read()
            session["offset"] = size
        except OSError:
            return ""
        return _to_plain(text)

    def _read_new_output(self, session: dict, cursor: str = "offset") -> str:
        log_file = session.get("log_file")
        if not log_file or not os.path.exists(log_file):
            return ""
        with self._log_lock:
            offset = session.get(cursor, 0)
            with open(log_file, encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                chunk = handle.read()
                session[cursor] = handle.tell()
        return chunk

    def _start_tail_reader(self, session: dict) -> None:
        """Stream a file-backed session to the UI without touching a pipe."""

        def tail() -> None:
            while True:
                chunk = self._read_new_output(session, cursor="stream_offset")
                if chunk:
                    try:
                        self._update_terminal_output(chunk)
                    except Exception:
                        logger.debug(
                            "terminal tail push failed", exc_info=True
                        )
                process = session.get("process")
                if process is None or process.poll() is not None:
                    chunk = self._read_new_output(
                        session, cursor="stream_offset"
                    )
                    if chunk:
                        try:
                            self._update_terminal_output(chunk)
                        except Exception:
                            logger.debug(
                                "terminal tail push failed", exc_info=True
                            )
                    session["running"] = False
                    return
                time.sleep(0.2)

        thread = threading.Thread(
            target=tail,
            name=f"shell-tail-{session['id']}",
            daemon=True,
        )
        thread.start()
        session["tail_thread"] = thread

    def _spawn_local(self, command: str, session_id: str) -> dict:
        os.makedirs(self._session_log_dir, exist_ok=True)
        log_file = self._session_log_file(session_id)

        with open(log_file, "ab") as output:
            output.write(
                (
                    f"--- {time.ctime()} | session {session_id} ---\n"
                    f"$ {command}\n"
                ).encode()
            )
            output.flush()
            start_offset = output.tell()

            kwargs: dict = {
                "shell": True,
                "stdin": subprocess.PIPE,
                "stdout": output,
                "stderr": subprocess.STDOUT,
                "cwd": self.working_dir,
                "env": self._get_env_vars(),
                "text": True,
            }
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                kwargs["start_new_session"] = True
            process = subprocess.Popen(command, **kwargs)

        pgid = None
        if os.name != "nt":
            try:
                pgid = os.getpgid(process.pid)
            except ProcessLookupError:
                pgid = None

        session = {
            "id": session_id,
            "process": process,
            "pgid": pgid,
            "command": command,
            "running": True,
            "log_file": log_file,
            "offset": start_offset,
            "stream_offset": start_offset,
            "started_at": time.time(),
            "backend": "local",
            "project": self._project_key(),
        }
        self.shell_sessions[session_id] = session
        shell_sessions.register(self._project_key(), session)
        return session

    def shell_exec(
        self,
        command: str,
        id: str | None = None,
        block: bool = True,
        timeout: float = DEFAULT_BLOCKING_TIMEOUT,
        **_ignored: object,
    ) -> str:
        r"""Executes a shell command in blocking or non-blocking mode.

        Args:
            command (str): The shell command to execute.
            id (str, optional): A unique identifier for the command's session.
                If not provided, a unique ID will be automatically generated.
            block (bool, optional): Determines the execution mode. Defaults to True.
                Use False for servers, watchers, and any command without a
                natural end.
            timeout (float, optional): Maximum wall-clock seconds to wait in
                blocking mode. Defaults to 10.

        Returns:
            str: The output of the command execution.

        Blocked commands (`rm`, `sudo`, `shutdown`, `dd`, `mkfs`, `git rm`,
        `find -delete`) return an error and are never executed.
        """
        # Tolerate stray kwargs. Weaker models sometimes pass a bare
        # `description` (conflating it with the message-integration
        # `message_description`, which the wrapper strips — `description` is
        # not), which otherwise raised `unexpected keyword argument
        # 'description'` and failed EVERY shell call, stalling the whole turn.
        if _ignored:
            logger.debug(
                "shell_exec ignoring stray kwargs: %s", list(_ignored)
            )
        if id is None:
            id = f"auto_{int(time.time() * 1000)}"

        # tier 3 is a hard block: approval cannot override it, so reject
        # before the Docker/local split or the venv activation prefix.
        assessment = assess_command(command)
        if assessment.blocked:
            logger.info(
                "Blocked tier-3 shell command",
                extra={
                    "api_task_id": self.api_task_id,
                    "tier": int(assessment.tier),
                    "reason": assessment.reason,
                },
            )
            return (
                "Error: Command blocked by the command policy. "
                f"{assessment.reason}. It is never executed, even with "
                "approval. Use a non-destructive alternative; if removal is "
                "genuinely required, ask the user to do it."
            )

        if self.use_docker_backend:
            return super().shell_exec(
                id=id, command=command, block=block, timeout=timeout
            )

        existing = shell_sessions.find(self._project_key(), id)
        if existing is not None and shell_sessions.is_running(existing):
            return (
                f"Error: Session '{id}' already exists and is running. "
                "Use a different ID or kill the existing session first."
            )

        if self.safe_mode:
            is_safe, message = self._sanitize_command(command)
            if not is_safe:
                return (
                    "Error: Command rejected by TerminalToolkit safe mode. "
                    f"{message}"
                )
            command = message

        env_path = self._get_venv_path()
        if env_path:
            if self.os_type == "Windows":
                activate = os.path.join(env_path, "Scripts", "activate.bat")
                command = f'call "{activate}" && {command}'
            else:
                activate = os.path.join(env_path, "bin", "activate")
                command = f'. "{activate}" && {command}'

        try:
            session = self._spawn_local(command, id)
        except Exception as exc:
            logger.warning("Failed to start shell session %s: %s", id, exc)
            return f"Error: Failed to start command: {exc}"

        if not block:
            self._start_tail_reader(session)
            return (
                f"Session '{id}' started in the background.\n\n"
                f"Use:\n  - shell_view('{id}') - new output\n"
                f"  - shell_kill_process('{id}') - terminate"
            )

        try:
            session["process"].wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            session["running"] = True
            self._start_tail_reader(session)
            tail = self._tail_text(session["log_file"], strip_header=True)
            return (
                f"Command still running after {timeout:g}s. Session '{id}'.\n"
                f"Read with shell_view('{id}'), stop with "
                f"shell_kill_process('{id}').\n"
                f"Last output:\n{tail or '(no output yet)'}"
            )

        session["running"] = False
        result = self._read_result(session)

        if result:
            try:
                self._update_terminal_output(result)
            except Exception:
                logger.debug("terminal result push failed", exc_info=True)
            return result

        return "Command executed successfully (no output)."

    def shell_view(self, id: str) -> str:
        r"""Retrieves new output from a background session without blocking.

        Args:
            id (str): The unique session ID returned by shell_exec.

        Returns:
            str: Output produced since the last call, or a status message.
        """
        session = shell_sessions.find(self._project_key(), id)
        if session is None:
            session = self.shell_sessions.get(id)
        if session is None or session.get("backend") == "docker":
            return super().shell_view(id)

        running = shell_sessions.is_running(session)
        chunk = self._read_new_output(session)
        if chunk:
            try:
                self._update_terminal_output(chunk)
            except Exception:
                logger.debug("terminal view push failed", exc_info=True)
            return (
                chunk if running else chunk + "\n\n--- SESSION TERMINATED ---"
            )

        if running:
            return (
                "[No new output]\n"
                "Session is running but idle. Actions could take:\n"
                "  - For interactive sessions: Send input "
                "with shell_write_to_process()\n"
                "  - For long tasks: Check again later (don't poll too frequently)"
            )
        return "--- SESSION TERMINATED (no new output) ---"

    def shell_kill_process(self, id: str) -> str:
        r"""Terminates a background session and the processes it started.

        Prefer this over `kill`/`pkill`/`taskkill`. The registry is in memory,
        so an id from before a brain restart is gone; if the port is still
        open, report it to the user rather than killing an unknown process.

        Args:
            id (str): The unique session ID returned by shell_exec.

        Returns:
            str: What was terminated, and whether its port was released.
        """
        session = shell_sessions.find(self._project_key(), id)
        if session is None:
            session = self.shell_sessions.get(id)
        if session is None or session.get("backend") == "docker":
            return super().shell_kill_process(id)

        ports = shell_sessions.ports_in_command(session.get("command", ""))
        outcome = shell_sessions.terminate_tree(session)
        shell_sessions.forget(self._project_key(), id)
        self.shell_sessions.pop(id, None)

        if outcome == "already exited":
            message = f"Session '{id}' had already exited."
        elif outcome == "no process":
            message = f"Session '{id}' had no live process."
        else:
            message = f"Process in session '{id}' has been terminated."

        if ports:
            still_open = shell_sessions.wait_for_ports_closed(ports)
            if still_open:
                message += (
                    " Port(s) still open: "
                    + ", ".join(str(port) for port in still_open)
                    + "."
                )
            else:
                message += (
                    " Port(s) "
                    + ", ".join(str(port) for port in ports)
                    + " are free."
                )
        return message

    def cleanup(self, remove_venv: bool = True):
        """Clean up all active sessions and optionally remove the virtual environment.

        Args:
            remove_venv: If True, removes the .venv or .initial_env folder created
                        by this toolkit. Defaults to True to prevent disk bloat.
        """
        # First call parent cleanup to kill all shell sessions
        super().cleanup()

        if not remove_venv:
            return

        # Remove cloned env (.venv) if it exists
        cloned_env_path = getattr(self, "cloned_env_path", None)
        if cloned_env_path and os.path.exists(cloned_env_path):
            try:
                shutil.rmtree(cloned_env_path)
                logger.info(
                    "Removed cloned venv",
                    extra={
                        "api_task_id": self.api_task_id,
                        "path": cloned_env_path,
                    },
                )
            except Exception as e:
                logger.warning(
                    "Failed to remove cloned venv",
                    extra={
                        "api_task_id": self.api_task_id,
                        "path": cloned_env_path,
                        "error": str(e),
                    },
                )

        # Remove initial env (.initial_env) if it exists
        initial_env_path = getattr(self, "initial_env_path", None)
        if initial_env_path and os.path.exists(initial_env_path):
            try:
                shutil.rmtree(initial_env_path)
                logger.info(
                    "Removed initial env",
                    extra={
                        "api_task_id": self.api_task_id,
                        "path": initial_env_path,
                    },
                )
            except Exception as e:
                logger.warning(
                    "Failed to remove initial env",
                    extra={
                        "api_task_id": self.api_task_id,
                        "path": initial_env_path,
                        "error": str(e),
                    },
                )

    @classmethod
    def shutdown(cls):
        if cls._thread_pool:
            cls._thread_pool.shutdown(wait=True)
            cls._thread_pool = None
