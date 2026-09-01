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

"""AI test-coverage tooling driven by the `lacuna` CLI.

This toolkit is a thin, structured wrapper around the `lacuna-cli` agent (see
the `lacuna-cli` skill's SKILL.md) for JavaScript/TypeScript projects. It lets
an agent:

  - read the skill's guidance (`read_test_skill`),
  - `analyze` coverage gaps (read-only),
  - `run` the suite (read-only),
  - `generate` tests to fill gaps (mutating -- gated under Ask mode),
  - `fix` failing tests (mutating -- gated under Ask mode).

`generate`/`fix` invoke a model and write files, so they are governance-gated;
`analyze`/`run`/`read_test_skill` are safe. Requires the `lacuna` CLI on PATH
and an initialized project (`.lacuna.json`); the tools surface a clear message
when either is missing rather than failing opaquely.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from camel.toolkits import BaseToolkit
from camel.toolkits.function_tool import FunctionTool

from app.agent.toolkit.abstract_toolkit import AbstractToolkit
from app.component.environment import env
from app.service.task import Agents

logger = logging.getLogger(__name__)

#: Mutating tools (invoke a model + write test files). Gated under Ask mode.
WRITE_TOOL_NAMES = {"generate_tests", "fix_failing_tests"}

_SKILL_NAME = "lacuna-cli"
_MAX_OUTPUT_CHARS = 20_000
#: generate/fix run an AI loop and can take minutes; analyze/run are quick.
_LONG_TIMEOUT = 900.0
_SHORT_TIMEOUT = 300.0


class TestRunnerToolkit(BaseToolkit, AbstractToolkit):
    """Structured wrapper around the `lacuna` AI test-coverage CLI."""

    agent_name: str = Agents.developer_agent

    def __init__(
        self,
        api_task_id: str,
        agent_name: str | None = None,
        working_directory: str | None = None,
        timeout: float | None = None,
    ) -> None:
        super().__init__(timeout=timeout)
        self.api_task_id = api_task_id
        if agent_name is not None:
            self.agent_name = agent_name
        if not working_directory:
            raise ValueError(
                "working_directory is required for TestRunnerToolkit; tests "
                "run within the task's project directory."
            )
        self.working_directory = str(Path(working_directory).expanduser())

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _skill_md_path(self) -> Path | None:
        """Locate the lacuna-cli skill's SKILL.md across known layouts."""
        candidates = []
        override = env("EIGENT_SKILLS_DIR", "")
        if override:
            candidates.append(Path(override) / _SKILL_NAME / "SKILL.md")
        home_skills = Path.home() / ".eigent"
        candidates.append(home_skills / "skills" / _SKILL_NAME / "SKILL.md")
        # user-scoped (~/.eigent/user_*/skills/lacuna-cli/SKILL.md)
        candidates.extend(
            sorted(home_skills.glob(f"user_*/skills/{_SKILL_NAME}/SKILL.md"))
        )
        # project-local (<workdir>/.eigent/skills/lacuna-cli/SKILL.md)
        candidates.append(
            Path(self.working_directory)
            / ".eigent"
            / "skills"
            / _SKILL_NAME
            / "SKILL.md"
        )
        for path in candidates:
            if path and path.is_file():
                return path
        return None

    def _lacuna_available(self) -> bool:
        return shutil.which("lacuna") is not None

    def _initialized(self) -> bool:
        return (Path(self.working_directory) / ".lacuna.json").is_file()

    def _run_lacuna(self, args: list[str], timeout: float) -> str:
        if not self._lacuna_available():
            return (
                "[lacuna error]: the 'lacuna' CLI is not installed / not on "
                "PATH. Install it with `npm install -g lacuna-cli`."
            )
        if not self._initialized():
            return (
                "[lacuna error]: this project is not initialized "
                "(no .lacuna.json). Run `lacuna init` once in the project "
                "first (interactive wizard) — see read_test_skill."
            )
        try:
            result = subprocess.run(
                ["lacuna", *args],
                cwd=self.working_directory,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return f"[lacuna error]: 'lacuna {' '.join(args)}' timed out."
        except Exception as exc:  # pragma: no cover - defensive
            return f"[lacuna error]: {exc}"

        out = ((result.stdout or "") + (result.stderr or "")).strip()
        if len(out) > _MAX_OUTPUT_CHARS:
            out = out[:_MAX_OUTPUT_CHARS] + "\n… [output truncated]"
        prefix = (
            ""
            if result.returncode == 0
            else (f"[lacuna exited {result.returncode}]\n")
        )
        return prefix + (out or "(no output)")

    # ------------------------------------------------------------------ #
    # Tools
    # ------------------------------------------------------------------ #

    def read_test_skill(self) -> str:
        """Return the lacuna-cli skill guidance (its SKILL.md).

        Read this first: it documents the analyze -> generate -> fix -> run
        workflow, flags, and prerequisites you should follow when working with
        tests via lacuna.

        Returns:
            str: The SKILL.md content, or a message if it can't be located.
        """
        path = self._skill_md_path()
        if not path:
            return (
                "[skill not found]: could not locate the lacuna-cli SKILL.md. "
                "Expected under ~/.eigent/skills/lacuna-cli/SKILL.md."
            )
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:  # pragma: no cover - defensive
            return f"[skill read error]: {exc}"
        if len(text) > _MAX_OUTPUT_CHARS:
            text = text[:_MAX_OUTPUT_CHARS] + "\n… [truncated]"
        return text

    def analyze_coverage(self, threshold: int = 0, scope: str = "") -> str:
        """Analyze test coverage and report gaps -- writes nothing.

        Args:
            threshold (int): Optional minimum coverage % bar (e.g. 90).
            scope (str): Optional scope, e.g. a path or '@diff:origin/main'
                to only consider changed lines.

        Returns:
            str: The coverage-gap report.
        """
        args = ["analyze"]
        if threshold:
            args += ["--threshold", str(int(threshold))]
        if scope.strip():
            args.append(scope.strip())
        return self._run_lacuna(args, _SHORT_TIMEOUT)

    def run_tests(self) -> str:
        """Run the full test suite and report coverage (no model involved).

        Returns:
            str: Test-run + coverage output.
        """
        return self._run_lacuna(["run"], _SHORT_TIMEOUT)

    def generate_tests(
        self,
        file: str = "",
        scope: str = "",
        dry_run: bool = False,
        workers: int = 0,
        model: str = "",
    ) -> str:
        """Generate tests to fill coverage gaps (writes test files).

        Runs lacuna's agent loop: analyze gaps, generate real behavioral tests,
        run them, and retry failures until they pass. Prefer `dry_run=True`
        first when the user wants to preview scope.

        Args:
            file (str): Optional single file to cover (e.g. src/utils/add.ts).
            scope (str): Optional scope, e.g. '@diff:origin/main'.
            dry_run (bool): Preview without writing when True.
            workers (int): Optional parallel workers (e.g. 8).
            model (str): Optional model override (e.g. 'claude').

        Returns:
            str: The generation output.
        """
        args = ["generate"]
        if file.strip():
            args += ["--file", file.strip()]
        if scope.strip():
            args.append(scope.strip())
        if dry_run:
            args.append("--dry-run")
        if workers:
            args += ["--workers", str(int(workers))]
        if model.strip():
            args += ["-m", model.strip()]
        return self._run_lacuna(args, _LONG_TIMEOUT)

    def fix_failing_tests(
        self,
        file: str = "",
        types: bool = False,
        fix_polluters: bool = False,
    ) -> str:
        """Repair failing tests with AI (edits test files).

        Args:
            file (str): Optional single failing test file to repair.
            types (bool): Also repair type-check errors when True.
            fix_polluters (bool): Also fix tests that pollute other suites.

        Returns:
            str: The fix output.
        """
        args = ["fix"]
        if file.strip():
            args += ["--file", file.strip()]
        if types:
            args.append("--types")
        if fix_polluters:
            args.append("--fix-polluters")
        return self._run_lacuna(args, _LONG_TIMEOUT)

    def get_tools(self) -> list[FunctionTool]:
        return [
            FunctionTool(self.read_test_skill),
            FunctionTool(self.analyze_coverage),
            FunctionTool(self.run_tests),
            FunctionTool(self.generate_tests),
            FunctionTool(self.fix_failing_tests),
        ]
