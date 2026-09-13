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

import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from camel.toolkits import FileToolkit as BaseFileToolkit

from app.agent.toolkit.abstract_toolkit import AbstractToolkit
from app.component.environment import env
from app.run_context import RunContext
from app.service.task import (
    ActionWriteFileData,
    Agents,
    get_task_lock,
    process_task,
)
from app.utils.listen.toolkit_listen import (
    _safe_put_queue,
    auto_listen_toolkit,
    listen_toolkit,
)
from app.utils.space_overlay_client import (
    path_write_lock,
    post_overlay_write,
    relative_to_workdir,
    run_context_for_task,
    sha256_of_file,
    should_record_overlay,
)


# ---------------------------------------------------------------------------
# Text fast-path for read_file.
#
# CAMEL's FileToolkit.read_file routes every file through MarkItDownLoader,
# whose SUPPORTED_FORMATS whitelist only covers rich documents (pdf, docx,
# xlsx, images, audio, csv/json/xml/txt/md). Source code (.tsx, .py, .rs, ...)
# therefore raises "Unsupported file format", and even whitelisted text formats
# get re-rendered as Markdown instead of being returned verbatim. We short
# circuit plain-text/code files and only fall back to MarkItDown for genuinely
# rich documents.
# ---------------------------------------------------------------------------

# Extensions we always treat as text even if `mimetypes` has no opinion.
_TEXT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".bash", ".c", ".cc", ".cfg", ".cjs", ".clj", ".conf", ".cpp",
        ".cs", ".css", ".csv", ".diff", ".env", ".erl", ".ex", ".exs",
        ".gql", ".go", ".graphql", ".h", ".hcl", ".hpp", ".hs", ".htm",
        ".html", ".ini", ".java", ".js", ".jsonc", ".jsx", ".kt", ".kts",
        ".less", ".log", ".lua", ".mjs", ".patch", ".php", ".pl", ".proto",
        ".py", ".pyi", ".r", ".rb", ".rs", ".rst", ".sass", ".scala",
        ".scss", ".sh", ".sql", ".svelte", ".swift", ".tf", ".tfvars",
        ".toml", ".ts", ".tsv", ".tsx", ".txt", ".vue", ".xml", ".yaml",
        ".yml", ".zsh", ".astro", ".mdx",
    }
)

# Extensionless files that are conventionally text.
_TEXT_FILENAMES: frozenset[str] = frozenset(
    {
        ".bashrc", ".dockerignore", ".editorconfig", ".env", ".gitattributes",
        ".gitignore", ".nvmrc", ".zshrc", "dockerfile", "gemfile", "license",
        "makefile", "procfile", "rakefile",
    }
)

_TEXT_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/javascript",
        "application/json",
        "application/toml",
        "application/x-sh",
        "application/x-yaml",
        "application/xml",
    }
)

# Refuse to slurp huge files into the agent's context window.
_MAX_TEXT_BYTES: int = 2 * 1024 * 1024  # 2 MB


@dataclass(frozen=True)
class OverlayWriteContext:
    run_context: RunContext
    rel_path: str
    target_path: Path


@dataclass(frozen=True)
class PendingOverlayWrite:
    run_context: RunContext
    rel_path: str
    target_path: Path
    base_hash: str | None
    status: Literal["added", "modified"]
    file_hash: str | None
    size: int
    mode: int


@auto_listen_toolkit(BaseFileToolkit)
class FileToolkit(BaseFileToolkit, AbstractToolkit):
    agent_name: str = Agents.document_agent

    def __init__(
        self,
        api_task_id: str,
        working_directory: str | None = None,
        timeout: float | None = None,
        default_encoding: str = "utf-8",
        backup_enabled: bool = True,
    ) -> None:
        if working_directory is None:
            working_directory = env(
                "file_save_path", os.path.expanduser("~/Downloads")
            )
        super().__init__(
            working_directory, timeout, default_encoding, backup_enabled
        )
        self.api_task_id = api_task_id

    @property
    def _encoding(self) -> str:
        return getattr(self, "default_encoding", None) or "utf-8"

    def _is_explicit_text(self, path: Path) -> bool:
        r"""True when the extension/filename is a known text or code format."""
        return (
            path.suffix.lower() in _TEXT_EXTENSIONS
            or path.name.lower() in _TEXT_FILENAMES
        )

    def _is_text_readable(self, path: Path) -> bool:
        r"""Heuristically decide whether ``path`` should be read as text.

        Order: extension/filename allowlist -> size guard -> mimetype guess ->
        null-byte / decode sniff. Explicit text extensions win even when the
        file is large (the reader truncates); only unknown files are rejected
        on size, so the agent's context window is never blown by a giant blob.
        """
        try:
            if not path.is_file():
                return False
            size = path.stat().st_size
        except OSError:
            return False

        if self._is_explicit_text(path):
            return True

        if size > _MAX_TEXT_BYTES:
            return False

        mime, _ = mimetypes.guess_type(str(path))
        if mime and (
            mime.startswith("text/") or mime in _TEXT_MIME_TYPES
        ):
            return True

        try:
            with path.open("rb") as handle:
                sample = handle.read(8192)
        except OSError:
            return False
        if b"\x00" in sample:
            return False
        try:
            sample.decode(self._encoding)
        except (UnicodeDecodeError, LookupError):
            return False
        return True

    def _read_text_file(self, path: Path) -> str:
        r"""Return the file's text with 1-based line numbers prefixed.

        Line numbers let the agent cite and edit exact lines without counting
        or re-reading the file. Files larger than the cap are truncated with a
        trailing marker instead of being refused.
        """
        try:
            with path.open("rb") as handle:
                raw = handle.read(_MAX_TEXT_BYTES + 1)
        except OSError as e:
            return f"Error reading file: {e}"

        truncated = len(raw) > _MAX_TEXT_BYTES
        text = raw[:_MAX_TEXT_BYTES].decode(
            self._encoding, errors="replace"
        )
        lines = text.splitlines()
        if truncated:
            lines.append(f"... [truncated at {_MAX_TEXT_BYTES} bytes]")
        if not lines:
            return ""
        width = len(str(len(lines)))
        return "\n".join(
            f"{number:>{width}}: {line}"
            for number, line in enumerate(lines, start=1)
        )

    def read_file(
        self, file_paths: str | list[str]
    ) -> str | dict[str, str]:
        r"""Read one or more files, preferring a plain-text fast-path.

        Text and source-code files are returned verbatim (with line numbers);
        rich documents (pdf, docx, xlsx, images, audio, ...) fall back to
        CAMEL's MarkItDown-based ``read_file``.

        Args:
            file_paths: A single path or a list of paths, relative or absolute.

        Returns:
            The file content as a string for a single path, or a dict keyed by
            the original paths for a list.
        """
        try:
            if isinstance(file_paths, str):
                resolved = self._resolve_existing_filepath(file_paths)
                if self._is_text_readable(resolved):
                    return self._read_text_file(resolved)
                return super().read_file(file_paths)

            resolved_paths = [
                self._resolve_existing_filepath(fp) for fp in file_paths
            ]
            result: dict[str, str] = {}
            rich_originals: list[str] = []
            rich_resolved: list[str] = []
            for original, resolved in zip(file_paths, resolved_paths):
                if self._is_text_readable(resolved):
                    result[original] = self._read_text_file(resolved)
                else:
                    rich_originals.append(original)
                    rich_resolved.append(str(resolved))

            if rich_resolved:
                rich = super().read_file(rich_resolved)
                if isinstance(rich, dict):
                    for original, resolved in zip(
                        rich_originals, rich_resolved
                    ):
                        result[original] = rich.get(
                            resolved, f"Failed to read file: {resolved}"
                        )
                else:
                    result[rich_originals[0]] = rich

            return result
        except Exception as e:
            return f"Error reading file(s): {e}"

    def _overlay_write_context(
        self, filename: str
    ) -> OverlayWriteContext | None:
        context = run_context_for_task(self.api_task_id)
        if context is None:
            return None
        resolved = relative_to_workdir(context, filename)
        if resolved is None:
            return None
        rel_path, target_path = resolved
        if not should_record_overlay(context, target_path):
            return None
        return OverlayWriteContext(context, rel_path, target_path)

    @listen_toolkit(
        BaseFileToolkit.write_to_file,
        lambda _,
        title,
        content,
        filename,
        encoding=None,
        use_latex=False: (
            f"write content to file: {filename} "
            # Line count as a machine-readable tag so the activity trace can
            # render a +N diff badge (the narration omits the content itself).
            f"[diff +"
            + str(
                (content.count("\n") + 1)
                if isinstance(content, str) and content
                else (len(content) if isinstance(content, list) else 0)
            )
            + " -0]"
        ),
    )
    def write_to_file(
        self,
        title: str,
        content: str | list[list[str]],
        filename: str,
        encoding: str | None = None,
        use_latex: bool = False,
    ) -> str:
        overlay_context = self._overlay_write_context(filename)
        if overlay_context is None:
            res = super().write_to_file(
                title, content, filename, encoding, use_latex
            )
        else:
            pending_overlay_write: PendingOverlayWrite | None = None
            with path_write_lock(
                overlay_context.run_context.space_id,
                overlay_context.run_context.project_id,
                overlay_context.run_context.run_id,
                overlay_context.rel_path,
            ):
                existed = overlay_context.target_path.exists()
                base_hash = sha256_of_file(overlay_context.target_path)
                res = super().write_to_file(
                    title, content, filename, encoding, use_latex
                )
                if "Content successfully written to file: " in res:
                    written_path = Path(
                        res.replace(
                            "Content successfully written to file: ", ""
                        )
                    )
                    if not written_path.is_absolute():
                        written_path = (
                            Path(self.working_directory) / written_path
                        )
                    written_hash = sha256_of_file(written_path)
                    written_stat = written_path.stat()
                    pending_overlay_write = PendingOverlayWrite(
                        run_context=overlay_context.run_context,
                        rel_path=overlay_context.rel_path,
                        target_path=written_path,
                        base_hash=base_hash,
                        status="modified" if existed else "added",
                        file_hash=written_hash,
                        size=written_stat.st_size,
                        mode=written_stat.st_mode,
                    )
            if pending_overlay_write is not None:
                post_overlay_write(
                    pending_overlay_write.run_context,
                    pending_overlay_write.rel_path,
                    pending_overlay_write.target_path,
                    base_hash=pending_overlay_write.base_hash,
                    status=pending_overlay_write.status,
                    file_hash=pending_overlay_write.file_hash,
                    size=pending_overlay_write.size,
                    mode=pending_overlay_write.mode,
                )
        if "Content successfully written to file: " in res:
            task_lock = get_task_lock(self.api_task_id)
            # Capture ContextVar value before creating async task
            current_process_task_id = process_task.get("")

            # Use _safe_put_queue to handle both sync and async contexts
            _safe_put_queue(
                task_lock,
                ActionWriteFileData(
                    process_task_id=current_process_task_id,
                    data=res.replace(
                        "Content successfully written to file: ", ""
                    ),
                ),
            )
        return res
