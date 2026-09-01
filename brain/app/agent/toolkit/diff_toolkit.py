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

"""Apply unified diffs to the working tree as a first-class operation.

Lets an agent make **surgical, reviewable** edits (a unified diff) instead of
rewriting whole files, which is what enables an editor-style "apply / reject"
review flow. Uses `git apply` when the working dir is a git repo (best fidelity,
supports `--check` for a dry run) and falls back to the `patch` CLI otherwise.
`apply_patch` mutates files, so it is governance-gated under Ask mode; the
`check`/`preview` path is read-only.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from camel.toolkits import BaseToolkit
from camel.toolkits.function_tool import FunctionTool

from app.agent.toolkit.abstract_toolkit import AbstractToolkit
from app.service.task import Agents

logger = logging.getLogger(__name__)

#: Mutating tool the assembler gates under Ask mode.
WRITE_TOOL_NAMES = {"apply_patch"}


class DiffToolkit(BaseToolkit, AbstractToolkit):
    """Apply/verify unified diffs within a single working directory."""

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
                "working_directory is required for DiffToolkit; patches must "
                "apply within the task's project directory."
            )
        self.working_directory = str(Path(working_directory).expanduser())

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _is_git_repo(self) -> bool:
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=self.working_directory,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return r.returncode == 0 and r.stdout.strip() == "true"
        except Exception:
            return False

    def _run(
        self, cmd: list[str], stdin: str | None = None
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            cwd=self.working_directory,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=self.timeout or 30.0,
        )

    def _apply(self, patch_text: str, check_only: bool) -> str:
        if not patch_text or not patch_text.strip():
            return "[diff error]: empty patch."
        # Normalize: unified diffs must end with a trailing newline.
        if not patch_text.endswith("\n"):
            patch_text += "\n"

        # Preferred path: `git apply` (respects .gitattributes, supports --check).
        if self._is_git_repo():
            args = ["git", "apply", "--whitespace=nowarn"]
            if check_only:
                args.append("--check")
            try:
                r = self._run(args, stdin=patch_text)
            except subprocess.TimeoutExpired:
                return "[diff error]: git apply timed out."
            if r.returncode == 0:
                return (
                    "Patch applies cleanly (no changes written)."
                    if check_only
                    else "Patch applied successfully."
                )
            return (
                "[diff error]: patch does not apply.\n"
                + (r.stderr or r.stdout or "").strip()
            )

        # Fallback: POSIX `patch`. It has no reliable pure dry-run, so for a
        # check we use --dry-run when available.
        with tempfile.NamedTemporaryFile(
            "w", suffix=".patch", delete=False, dir=self.working_directory
        ) as fh:
            fh.write(patch_text)
            patch_path = fh.name
        try:
            args = ["patch", "-p1", "-i", patch_path]
            if check_only:
                args.append("--dry-run")
            try:
                r = self._run(args)
            except FileNotFoundError:
                return (
                    "[diff error]: not a git repo and the 'patch' CLI is "
                    "unavailable; cannot apply the diff."
                )
            except subprocess.TimeoutExpired:
                return "[diff error]: patch timed out."
            if r.returncode == 0:
                return (
                    "Patch applies cleanly (no changes written)."
                    if check_only
                    else "Patch applied successfully."
                )
            return (
                "[diff error]: patch does not apply.\n"
                + (r.stdout or r.stderr or "").strip()
            )
        finally:
            try:
                Path(patch_path).unlink(missing_ok=True)
            except Exception:  # pragma: no cover - defensive
                pass

    # ------------------------------------------------------------------ #
    # Tools
    # ------------------------------------------------------------------ #

    def check_patch(self, patch: str) -> str:
        """Dry-run a unified diff to verify it applies -- writes nothing.

        Args:
            patch (str): A unified diff (git-style, with `---`/`+++`/`@@`
                hunks and paths relative to the working directory root).

        Returns:
            str: Whether the patch applies cleanly, or the rejection reason.
        """
        return self._apply(patch, check_only=True)

    def apply_patch(self, patch: str) -> str:
        """Apply a unified diff to the working tree.

        Prefer this over rewriting whole files: it produces a small, reviewable
        change. Run `check_patch` first if unsure it applies.

        Args:
            patch (str): A unified diff (git-style, with `---`/`+++`/`@@`
                hunks and paths relative to the working directory root).

        Returns:
            str: Success, or the reason the patch could not be applied.
        """
        return self._apply(patch, check_only=False)

    def get_tools(self) -> list[FunctionTool]:
        return [
            FunctionTool(self.check_patch),
            FunctionTool(self.apply_patch),
        ]
