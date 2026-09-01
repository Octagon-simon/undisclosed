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

"""Project understanding via repomix.

Gives the agent a compact, AI-friendly digest of the current project's codebase
(structure + key code, tree-sitter compressed) so it can understand the repo in
one call instead of many grep/file searches. The digest is cached per project
(keyed by git HEAD) under ~/.eigent/project-context, so repeat calls are instant
and it only regenerates when the code changes (or refresh=True).

Uses `npx repomix` (no install/setup); FAIL-SOFT — if repomix/npx isn't available
the tool returns a clear note so the agent falls back to normal search.
"""

import hashlib
import logging
import shutil
import subprocess
from pathlib import Path

from camel.toolkits import FunctionTool

from app.agent.toolkit.abstract_toolkit import AbstractToolkit
from app.service.task import Agents

logger = logging.getLogger("project_context_toolkit")

# Cap the digest we return so it never blows the context window. repomix
# --compress already trims heavily; this is a final safety bound.
_MAX_DIGEST_CHARS = 60_000
def _context_root() -> Path:
    return Path.home() / ".eigent" / "project-context"


def _git_head(workdir: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", workdir, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        head = out.stdout.strip()
        if head:
            return head[:12]
    except Exception:  # noqa: BLE001
        pass
    return "nohead"


class ProjectContextToolkit(AbstractToolkit):
    """`understand_project` — a cached repomix digest of the workspace."""

    agent_name: str = Agents.single_agent

    def __init__(
        self,
        api_task_id: str,
        working_directory: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        self.api_task_id = api_task_id
        self.working_directory = working_directory
        if agent_name is not None:
            self.agent_name = agent_name

    def _cache_file(self, workdir: str) -> Path:
        key = hashlib.sha256(workdir.encode("utf-8")).hexdigest()[:16]
        return _context_root() / key / f"{_git_head(workdir)}.md"

    def _skeleton_map(self) -> str:
        """Structure-first index of the workspace (~1.5k tokens, no bodies).

        Uses the tree-sitter CodeQueryToolkit under the hood; fail-soft if
        tree-sitter is unavailable (then the agent falls back to normal search).
        """
        try:
            from app.agent.toolkit.code_query_toolkit import CodeQueryToolkit

            tk = CodeQueryToolkit(
                api_task_id=self.api_task_id,
                working_directory=self.working_directory,
            )
            map_text = tk.skeleton_map()
            if map_text and "No source files" not in map_text:
                return (
                    f"(structure-first skeleton map — call context_at(path, line) "
                    f"to read any symbol body on demand)\n\n{map_text}"
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("skeleton map failed, falling back to digest: %s", exc)
        # Tree-sitter unavailable or empty workspace — fall back to the dense
        # repomix digest (full=True) so the agent still gets whole-repo
        # orientation. No recursion because full=True bypasses this branch.
        return self.understand_project(full=True)

    def understand_project(
        self,
        refresh: bool = False,
        focus: str | None = None,
        full: bool = False,
    ) -> str:
        """Get a compact, AI-friendly understanding of the CURRENT project's
        codebase — its file structure plus the key code, compressed. Call this
        ONCE up front to understand the repository instead of running many
        grep/file searches; it's cached per project so repeat calls are instant.

        STRUCTURE-FIRST, FETCH-ON-DEMAND (default): by default this returns a
        cheap tree-sitter *skeleton map* (~1.5k tokens) — module/class/function
        signatures with no bodies — so the agent learns *where* things live
        before reading them. Use ``context_at`` to fetch the exact slice of any
        symbol the skeleton points at. This replaces the old behavior of always
        dumping a whole-repo repomix blob into the context window (the primary
        token burner).

        Set ``full=True`` (or pass ``focus=``) to get the dense repomix digest
        for rare whole-repo orientation needs.

        Args:
            refresh (bool): Regenerate the digest even if a cached one exists
                (use after significant code changes). Defaults to False.
            focus (str | None): Optional glob to narrow the scan, e.g.
                'src/**/*.ts' or 'backend/app/**'. Defaults to the whole repo.
            full (bool): Return the full repomix digest instead of the skeleton
                map. Defaults to False (structure-first).

        Returns:
            str: A compressed digest of the codebase (structure + key code), or a
                note to fall back to normal search if it can't be generated.
        """
        workdir = self.working_directory
        if not workdir or not Path(workdir).is_dir():
            return (
                "No workspace folder is open, so there's no project to scan. "
                "Use the normal file/search tools instead."
            )

        # STRUCTURE-FIRST: unless the caller explicitly asked for the dense
        # digest, return the cheap tree-sitter skeleton map instead of the 60k
        # repomix blob. The agent reads this to locate symbols, then uses
        # context_at to fetch implementation slices on demand.
        if not full and not focus:
            return self._skeleton_map()

        cache_file = self._cache_file(workdir)
        if not refresh and not focus and cache_file.exists():
            try:
                cached = cache_file.read_text(encoding="utf-8")
                return f"(cached project digest)\n\n{cached}"
            except Exception:  # noqa: BLE001
                pass

        if shutil.which("npx") is None:
            return (
                "Could not build a project digest (npx/repomix unavailable). "
                "Fall back to the normal file/search tools."
            )

        cmd = [
            "npx",
            "--yes",
            "repomix@latest",
            "--compress",
            "--stdout",
            "--quiet",
        ]
        if focus:
            cmd += ["--include", focus]
        try:
            proc = subprocess.run(
                cmd,
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=180,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("repomix run failed: %s", exc)
            return (
                "Could not build a project digest (repomix failed). Fall back "
                "to the normal file/search tools."
            )

        digest = (proc.stdout or "").strip()
        if not digest:
            return (
                "The project digest came back empty. Fall back to the normal "
                "file/search tools."
            )

        truncated = False
        if len(digest) > _MAX_DIGEST_CHARS:
            digest = digest[:_MAX_DIGEST_CHARS]
            truncated = True

        # Cache full-repo digests (not focused subsets).
        if not focus:
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(digest, encoding="utf-8")
            except Exception:  # noqa: BLE001
                logger.debug("failed to cache project digest", exc_info=True)

        note = (
            "\n\n[Digest truncated — call understand_project(focus=...) to zoom "
            "into a specific area.]"
            if truncated
            else ""
        )
        return f"{digest}{note}"

    def get_tools(self) -> list[FunctionTool]:
        return [FunctionTool(self.understand_project)]

    @classmethod
    def toolkit_name(cls) -> str:
        return "Project Context Toolkit"
