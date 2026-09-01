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

"""Local git operations over the project working directory.

Distinct from `GithubToolkit` (the GitHub REST API): this drives the local
`git` CLI in the task's working directory, so agents can inspect and record
their own code changes. Read operations (status/diff/log/show/blame/branch
list) are safe; the mutating operations (add/commit/create branch/stash) are
gated by the governance layer when Ask mode is enabled -- see
`factory/toolkit_assembler.py`, which wraps `WRITE_TOOL_NAMES` below.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from camel.toolkits import BaseToolkit
from camel.toolkits.function_tool import FunctionTool

from app.agent.toolkit.abstract_toolkit import AbstractToolkit
from app.service.task import Agents

logger = logging.getLogger(__name__)

#: Tools that mutate the repository. The assembler gates these under Ask mode.
WRITE_TOOL_NAMES = {
    "git_add",
    "git_commit",
    "git_create_branch",
    "git_checkout",
    "git_stash",
}

#: Cap command output so a huge diff/log can't blow the model context.
_MAX_OUTPUT_CHARS = 20_000


class GitToolkit(BaseToolkit, AbstractToolkit):
    """Local git CLI wrapper scoped to a single working directory."""

    agent_name: str = Agents.developer_agent

    def __init__(
        self,
        api_task_id: str,
        agent_name: str | None = None,
        working_directory: str | None = None,
        timeout: float | None = 30.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.api_task_id = api_task_id
        if agent_name is not None:
            self.agent_name = agent_name
        if not working_directory:
            raise ValueError(
                "working_directory is required for GitToolkit; git operations "
                "must be scoped to the task's project directory."
            )
        self.working_directory = str(Path(working_directory).expanduser())

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _run_git(self, args: list[str]) -> str:
        """Run `git <args>` in the working dir; return combined output."""
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.working_directory,
                capture_output=True,
                text=True,
                timeout=self.timeout or 30.0,
            )
        except FileNotFoundError:
            return "[git error]: 'git' is not installed or not on PATH."
        except subprocess.TimeoutExpired:
            return f"[git error]: 'git {' '.join(args)}' timed out."
        except Exception as exc:  # pragma: no cover - defensive
            return f"[git error]: {exc}"

        out = (result.stdout or "") + (
            f"\n{result.stderr}" if result.stderr else ""
        )
        out = out.strip()
        if result.returncode != 0:
            return (
                f"[git exited {result.returncode}]\n{out}"
                if out
                else (f"[git exited {result.returncode}] (no output)")
            )
        if not out:
            return "(no output)"
        if len(out) > _MAX_OUTPUT_CHARS:
            out = out[:_MAX_OUTPUT_CHARS] + "\n… [output truncated]"
        return out

    # ------------------------------------------------------------------ #
    # Read-only tools
    # ------------------------------------------------------------------ #

    def git_status(self) -> str:
        """Show the working tree status (staged, unstaged, untracked).

        Returns:
            str: `git status` short-format output.
        """
        return self._run_git(["status", "--short", "--branch"])

    def git_diff(self, path: str = "", staged: bool = False) -> str:
        """Show changes not yet committed.

        Args:
            path (str): Optional file/dir to limit the diff to.
            staged (bool): When True, show staged changes (`--cached`).

        Returns:
            str: Unified diff.
        """
        args = ["diff"]
        if staged:
            args.append("--cached")
        if path:
            args += ["--", path]
        return self._run_git(args)

    def git_log(self, max_count: int = 15, path: str = "") -> str:
        """Show recent commit history (one line per commit).

        Args:
            max_count (int): Number of commits to show (default 15).
            path (str): Optional file/dir to limit history to.

        Returns:
            str: Oneline log with short hashes, authors, and relative dates.
        """
        safe_count = max(1, min(int(max_count or 15), 200))
        args = [
            "log",
            f"-n{safe_count}",
            "--pretty=format:%h %ad | %an | %s",
            "--date=relative",
        ]
        if path:
            args += ["--", path]
        return self._run_git(args)

    def git_show(self, ref: str = "HEAD") -> str:
        """Show a commit's metadata and diff.

        Args:
            ref (str): Commit-ish to show (default HEAD).

        Returns:
            str: `git show` output for the ref.
        """
        return self._run_git(["show", "--stat", "--patch", ref or "HEAD"])

    def git_blame(
        self, file: str, start_line: int = 0, end_line: int = 0
    ) -> str:
        """Show who last changed each line of a file.

        Args:
            file (str): Path to the file to blame.
            start_line (int): Optional first line (1-indexed).
            end_line (int): Optional last line (1-indexed).

        Returns:
            str: `git blame` output.
        """
        if not file:
            return "[git error]: 'file' is required for git_blame."
        args = ["blame"]
        if start_line and end_line:
            args += ["-L", f"{int(start_line)},{int(end_line)}"]
        args += ["--", file]
        return self._run_git(args)

    def git_branch_list(self) -> str:
        """List local branches (current branch marked with '*').

        Returns:
            str: `git branch` output.
        """
        return self._run_git(["branch", "--verbose"])

    # ------------------------------------------------------------------ #
    # Mutating tools (governance-gated under Ask mode)
    # ------------------------------------------------------------------ #

    def git_add(self, paths: str = ".") -> str:
        """Stage changes for commit.

        Args:
            paths (str): Space-separated paths to stage (default all: '.').

        Returns:
            str: Status after staging.
        """
        targets = paths.split() if paths.strip() else ["."]
        add_result = self._run_git(["add", *targets])
        if add_result.startswith("[git exited") or add_result.startswith(
            "[git error]"
        ):
            return add_result
        return self.git_status()

    def git_commit(self, message: str) -> str:
        """Create a commit from the staged changes.

        Args:
            message (str): The commit message.

        Returns:
            str: Result of the commit.
        """
        if not message or not message.strip():
            return "[git error]: a non-empty commit message is required."
        return self._run_git(["commit", "-m", message])

    def git_create_branch(self, name: str, checkout: bool = True) -> str:
        """Create a new branch (optionally switching to it).

        Args:
            name (str): New branch name.
            checkout (bool): When True (default), switch to the new branch.

        Returns:
            str: Result of the branch creation.
        """
        if not name or not name.strip():
            return "[git error]: a branch name is required."
        if checkout:
            return self._run_git(["checkout", "-b", name.strip()])
        return self._run_git(["branch", name.strip()])

    def git_checkout(self, ref: str) -> str:
        """Switch to an existing branch or restore working-tree files.

        Args:
            ref (str): Branch name or path/ref to check out.

        Returns:
            str: Result of the checkout.
        """
        if not ref or not ref.strip():
            return "[git error]: a branch/ref is required for git_checkout."
        return self._run_git(["checkout", ref.strip()])

    def git_stash(self, action: str = "push", message: str = "") -> str:
        """Stash or restore local changes.

        Args:
            action (str): One of 'push' (default), 'pop', 'list', 'drop'.
            message (str): Optional message when action is 'push'.

        Returns:
            str: Result of the stash operation.
        """
        action = (action or "push").strip().lower()
        if action not in {"push", "pop", "list", "drop"}:
            return "[git error]: action must be one of push, pop, list, drop."
        args = ["stash", action]
        if action == "push" and message.strip():
            args += ["-m", message.strip()]
        return self._run_git(args)

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #

    def get_tools(self) -> list[FunctionTool]:
        return [
            FunctionTool(self.git_status),
            FunctionTool(self.git_diff),
            FunctionTool(self.git_log),
            FunctionTool(self.git_show),
            FunctionTool(self.git_blame),
            FunctionTool(self.git_branch_list),
            FunctionTool(self.git_add),
            FunctionTool(self.git_commit),
            FunctionTool(self.git_create_branch),
            FunctionTool(self.git_checkout),
            FunctionTool(self.git_stash),
        ]
