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

"""Structured code search + directory listing.

Purpose-built retrieval primitives so the agent finds code in ONE targeted call
instead of spraying `shell_exec("grep …")` / `ls` commands. `grep_search` shells
out to ripgrep (as an argv list — NOT a shell pipeline, so no escaping pitfalls)
with a hard result cap; it falls back to `grep -rn` then a pure-Python walk when
`rg` isn't installed. Gitignore-noise dirs (.git, node_modules, dist, build, …)
are always excluded. Results carry file:line:text so the model can answer from
the snippet alone, or follow up with a bounded file read.
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path

from camel.toolkits import FunctionTool
from camel.toolkits.base import BaseToolkit

from app.agent.toolkit.abstract_toolkit import AbstractToolkit
from app.service.task import Agents
from app.utils.listen.toolkit_listen import auto_listen_toolkit

logger = logging.getLogger("code_search_toolkit")

# Cap results so one call can't flood the context window (the thing that makes a
# model distrust a big search and re-run it). ~60 lines is plenty to orient.
_MAX_MATCHES = 60
_MAX_DIR_ENTRIES = 200
_SEARCH_TIMEOUT_S = 20

# High-churn / vendored dirs we never want in code search or listings.
_IGNORE_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".venv",
    "venv",
    "__pycache__",
    ".turbo",
    ".cache",
    "coverage",
    ".idea",
    ".vscode",
}


@auto_listen_toolkit(BaseToolkit)
class CodeSearchToolkit(BaseToolkit, AbstractToolkit):
    """Fast, capped code search + directory listing for code navigation."""

    agent_name: str = Agents.single_agent

    def __init__(
        self,
        api_task_id: str,
        working_directory: str | None = None,
        agent_name: str | None = None,
        timeout: float | None = None,
    ) -> None:
        super().__init__(timeout)
        self.api_task_id = api_task_id
        self.working_directory = working_directory
        if agent_name is not None:
            self.agent_name = agent_name

    def _root(self) -> Path:
        root = Path(self.working_directory) if self.working_directory else Path.cwd()
        return root if root.is_dir() else Path.cwd()

    def _resolve(self, path: str | None) -> Path:
        root = self._root()
        if not path:
            return root
        p = Path(path)
        return p if p.is_absolute() else (root / path)

    def _rel(self, p: str) -> str:
        try:
            return str(Path(p).resolve().relative_to(self._root().resolve()))
        except Exception:
            return p

    def grep_search(
        self,
        query: str,
        path: str | None = None,
        is_regex: bool = False,
        case_insensitive: bool = False,
        includes: list[str] | None = None,
    ) -> str:
        """Search file CONTENTS for `query` and return matching `file:line: text`
        rows. Use this to find where a symbol/string/pattern appears — prefer it
        over `shell_exec` with grep/find/cat. For a symbol's definition or its
        references, prefer the tree-sitter tools (`find_symbol`,
        `find_references`) instead; use this for free-text/string matches.

        Args:
            query (str): Text to find. Treated as a literal unless `is_regex`.
            path (str | None): File or directory to search under (relative to the
                workspace, or absolute). Defaults to the whole workspace.
            is_regex (bool): Treat `query` as a regular expression.
            case_insensitive (bool): Case-insensitive match.
            includes (list[str] | None): Optional glob filters (e.g.
                ["*.ts", "*.tsx"]) to limit which files are searched.

        Returns:
            str: Up to ~60 `relpath:line: text` rows, or a "No matches" note.
        """
        q = (query or "").strip()
        if not q:
            return "grep_search: `query` is required."
        target = self._resolve(path)
        if not target.exists():
            return f"grep_search: path not found: {path}"

        rows = self._run_ripgrep(q, target, is_regex, case_insensitive, includes)
        if rows is None:
            rows = self._run_grep(q, target, is_regex, case_insensitive, includes)
        if rows is None:
            rows = self._run_python(q, target, is_regex, case_insensitive, includes)

        if not rows:
            where = self._rel(str(target))
            return f'No matches for "{q}" in {where}.'
        capped = rows[:_MAX_MATCHES]
        header = f'{len(capped)}{"+" if len(rows) > _MAX_MATCHES else ""} match(es) for "{q}":'
        lines = [header, *capped]
        if len(rows) > _MAX_MATCHES:
            lines.append(
                f"… (capped at {_MAX_MATCHES}; narrow with `path`/`includes` for the rest)"
            )
        return "\n".join(lines)

    def _run_ripgrep(self, q, target, is_regex, ci, includes):
        rg = shutil.which("rg")
        if not rg:
            return None
        args = [
            rg,
            "--no-heading",
            "--line-number",
            "--color",
            "never",
            "--max-columns",
            "300",
            "--max-count",
            "20",  # per-file cap
        ]
        if ci:
            args.append("-i")
        if not is_regex:
            args.append("-F")
        for d in _IGNORE_DIRS:
            args += ["-g", f"!**/{d}/**"]
        for g in includes or []:
            args += ["-g", g]
        args += ["--", q, str(target)]
        try:
            proc = subprocess.run(
                args,
                cwd=str(self._root()),
                capture_output=True,
                text=True,
                timeout=_SEARCH_TIMEOUT_S,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("ripgrep failed (%s); falling back", exc)
            return None
        # rg exit 1 = no matches (not an error); >1 = real error -> fall back.
        if proc.returncode not in (0, 1):
            logger.debug("ripgrep rc=%s: %s", proc.returncode, proc.stderr[:200])
            return None
        return self._format_lines(proc.stdout)

    def _run_grep(self, q, target, is_regex, ci, includes):
        grep = shutil.which("grep")
        if not grep:
            return None
        args = [grep, "-rn", "--color=never"]
        if ci:
            args.append("-i")
        if not is_regex:
            args.append("-F")
        for d in _IGNORE_DIRS:
            args.append(f"--exclude-dir={d}")
        for g in includes or []:
            args.append(f"--include={g}")
        args += ["--", q, str(target)]
        try:
            proc = subprocess.run(
                args,
                cwd=str(self._root()),
                capture_output=True,
                text=True,
                timeout=_SEARCH_TIMEOUT_S,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("grep failed (%s); falling back", exc)
            return None
        if proc.returncode not in (0, 1):
            return None
        return self._format_lines(proc.stdout)

    def _run_python(self, q, target, is_regex, ci, includes):
        import fnmatch
        import re

        try:
            pattern = re.compile(q, re.IGNORECASE if ci else 0) if is_regex else None
        except re.error:
            pattern = None
        needle = q.lower() if ci else q
        rows: list[str] = []
        files: list[Path] = []
        if target.is_file():
            files = [target]
        else:
            for dirpath, dirnames, filenames in os.walk(target):
                dirnames[:] = [d for d in dirnames if d not in _IGNORE_DIRS]
                for fn in filenames:
                    if includes and not any(
                        fnmatch.fnmatch(fn, g) for g in includes
                    ):
                        continue
                    files.append(Path(dirpath) / fn)
                if len(files) > 5000:
                    break
        for fp in files:
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as fh:
                    for i, line in enumerate(fh, start=1):
                        hit = (
                            pattern.search(line)
                            if pattern is not None
                            else (needle in (line.lower() if ci else line))
                        )
                        if hit:
                            rows.append(f"{self._rel(str(fp))}:{i}: {line.rstrip()[:300]}")
                            if len(rows) >= _MAX_MATCHES + 1:
                                return rows
            except Exception:  # noqa: BLE001
                continue
        return rows

    def _format_lines(self, stdout: str) -> list[str]:
        rows: list[str] = []
        for line in stdout.splitlines():
            if not line.strip():
                continue
            # rg/grep emit "<abs-or-rel path>:<line>:<text>"; relativize the path.
            parts = line.split(":", 2)
            if len(parts) == 3:
                rows.append(f"{self._rel(parts[0])}:{parts[1]}: {parts[2].strip()[:300]}")
            else:
                rows.append(line[:320])
            if len(rows) >= _MAX_MATCHES + 1:
                break
        return rows

    def list_dir(self, path: str | None = None) -> str:
        """List the immediate contents of a directory (one level, no recursive
        walk). Use this to discover a folder's files/subfolders instead of
        `shell_exec("ls")`. High-churn dirs (.git, node_modules, …) are skipped.

        Args:
            path (str | None): Directory relative to the workspace (or absolute).
                Defaults to the workspace root.

        Returns:
            str: `dir/` and `file (size)` entries, directories first.
        """
        target = self._resolve(path)
        if not target.exists():
            return f"list_dir: path not found: {path}"
        if not target.is_dir():
            return f"list_dir: not a directory: {path}"
        dirs: list[str] = []
        files: list[str] = []
        try:
            for entry in sorted(os.scandir(target), key=lambda e: e.name.lower()):
                if entry.name in _IGNORE_DIRS:
                    continue
                if entry.is_dir():
                    dirs.append(f"{entry.name}/")
                else:
                    try:
                        size = entry.stat().st_size
                    except Exception:  # noqa: BLE001
                        size = 0
                    files.append(f"{entry.name} ({_human_size(size)})")
        except Exception as exc:  # noqa: BLE001
            return f"list_dir: failed to read {path}: {exc}"
        entries = [*dirs, *files]
        where = self._rel(str(target))
        if not entries:
            return f"{where}/ is empty (or only ignored dirs)."
        capped = entries[:_MAX_DIR_ENTRIES]
        head = f"{where}/ — {len(dirs)} dir(s), {len(files)} file(s):"
        out = [head, *capped]
        if len(entries) > _MAX_DIR_ENTRIES:
            out.append(f"… (capped at {_MAX_DIR_ENTRIES})")
        return "\n".join(out)

    def get_tools(self) -> list[FunctionTool]:
        return [FunctionTool(self.grep_search), FunctionTool(self.list_dir)]

    @classmethod
    def get_can_use_tools(
        cls,
        api_task_id: str,
        working_directory: str | None = None,
        agent_name: str | None = None,
    ) -> list[FunctionTool]:
        inst = cls(api_task_id, working_directory, agent_name)
        return inst.get_tools()

    @classmethod
    def toolkit_name(cls) -> str:
        return "CodeSearchToolkit"


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)}B"
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}GB"
