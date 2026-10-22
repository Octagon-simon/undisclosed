# Copyright (c) 2026 Simon Ugorji

"""Deterministic test-coverage gap + diff tooling -- **no external LLM token
and no `lacuna` CLI install required**.

This toolkit is the in-product equivalent of "lacuna analyze": it detects the
project's test runner, runs the suite WITH coverage, parses the coverage report,
and reports the uncovered files/lines/functions. In ``@diff[:<ref>]`` mode it
reports Codecov-style *patch* coverage -- only the lines changed vs the base ref.

The process is ported from lacuna's own ``analyze`` pipeline (its
detector / runner / coverage / git-diff stages); that logic lives here so the
workflow never shells out to, or depends on, the ``lacuna`` binary. Nothing
calls a model: everything is deterministic. The tools are READ-ONLY (they never
write source or test files), so there is no Ask-mode gate.

The full ``generate``/``fix`` AI loop is intentionally NOT part of this workflow.
It lives in the ``lacuna-cli`` skill for callers who want it (``read_test_skill``
returns that skill's guidance). This toolkit only does coverage gaps + the diff
check, which is what the testing / verification flow needs.

Tools:

  - ``read_test_skill``   -- the lacuna-cli skill's SKILL.md (guidance / doc).
  - ``coverage_gap_plan`` -- the gap plan (defaults to the changed-lines lens
                             against ``main``, like a patch-coverage gate; pass
                             ``base='origin/develop'`` for another branch).
  - ``run_tests``         -- run the suite with coverage and pair it with the
                             same gap plan.

An optional ``.lacuna.json`` (or ``.lacunarc[.json]`` / a ``package.json``
``lacuna`` key) can pin ``testRunner`` / ``testCommand`` / ``coverageCommand`` /
``coverageDir`` / ``coverageFormat`` / ``sourceDir`` / ``threshold`` /
``coverageTimeout``; detection and defaults mirror lacuna's config schema when
it is absent.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from camel.toolkits import BaseToolkit
from camel.toolkits.function_tool import FunctionTool

from app.agent.toolkit.abstract_toolkit import AbstractToolkit
from app.component.environment import env
from app.service.task import Agents

logger = logging.getLogger(__name__)

#: Read-only: this toolkit runs the suite but never writes source/test files,
#: so there is no Ask-mode gate.
WRITE_TOOL_NAMES: set[str] = set()

_SKILL_NAME = "lacuna-cli"
_MAX_OUTPUT_CHARS = 20_000
_GIT_TIMEOUT = 120.0
_DEFAULT_THRESHOLD = 80
#: How much of the suite output to echo when the run fails.
_FAILURE_TAIL_CHARS = 1500
#: Extensions that can carry patch coverage. Unlike lacuna (JS/TS only), the
#: diff lens has to cover every runner this toolkit detects, or editing a
#: `.py` file reports "nothing changed" and a vacuous 100% patch.
_PATCH_EXTENSIONS = (
    "ts",
    "tsx",
    "js",
    "jsx",
    "mts",
    "cts",
    "mjs",
    "cjs",
    "py",
    "go",
    "rs",
    "rb",
    "php",
    "java",
    "kt",
    "kts",
    "swift",
    "cs",
    "vue",
    "svelte",
)
_SOURCE_EXT_RE = re.compile(rf"\.(?:{'|'.join(_PATCH_EXTENSIONS)})$")
#: Extensions walked when looking for source files with no coverage record.
_SOURCE_EXTENSIONS = {"." + ext for ext in _PATCH_EXTENSIONS}
#: Test files: `foo.test.ts`, `foo.spec.ts`, `test_foo.py`, `foo_test.go`.
_TEST_FILE_RE = re.compile(r"(?:[._](?:test|spec)\.[^.]+$)|(?:^test_[^/]+$)")
#: Refs are interpolated into a git command -- allow only ref-shaped strings.
_SAFE_REF_RE = re.compile(r"[\w\-./@~^{}]+")


# --------------------------------------------------------------------------- #
# Runner defaults (ported from lacuna's detector)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _RunnerSpec:
    test_runner: str
    language: str
    coverage_command: str
    test_command: str


_RUNNERS: dict[str, _RunnerSpec] = {
    "vitest": _RunnerSpec(
        "vitest", "typescript", "npx vitest run --coverage", "npx vitest run"
    ),
    "jest": _RunnerSpec("jest", "typescript", "npx jest --coverage", "npx jest"),
    "mocha": _RunnerSpec("mocha", "javascript", "npx nyc mocha", "npx mocha"),
    "pytest": _RunnerSpec(
        "pytest",
        "python",
        "python -m pytest --cov --cov-report=lcov",
        "python -m pytest",
    ),
    "go-test": _RunnerSpec(
        "go-test",
        "go",
        "go test ./... -coverprofile=coverage/lcov.info",
        "go test ./...",
    ),
    "cargo-test": _RunnerSpec(
        "cargo-test",
        "rust",
        "cargo tarpaulin --out Lcov --output-dir coverage",
        "cargo test",
    ),
    "rspec": _RunnerSpec("rspec", "ruby", "bundle exec rspec", "bundle exec rspec"),
    "phpunit": _RunnerSpec(
        "phpunit",
        "php",
        "./vendor/bin/phpunit --coverage-clover coverage/clover.xml",
        "./vendor/bin/phpunit",
    ),
    "pest": _RunnerSpec(
        "pest",
        "php",
        "./vendor/bin/pest --coverage --coverage-clover coverage/clover.xml",
        "./vendor/bin/pest",
    ),
    "dotnet-test": _RunnerSpec(
        "dotnet-test",
        "csharp",
        'dotnet test --collect:"XPlat Code Coverage"',
        "dotnet test",
    ),
    "gradle-test": _RunnerSpec(
        "gradle-test", "java", "./gradlew test jacocoTestReport", "./gradlew test"
    ),
    "maven-test": _RunnerSpec(
        "maven-test", "java", "mvn test jacoco:report", "mvn test"
    ),
    "swift-test": _RunnerSpec(
        "swift-test", "swift", "swift test --enable-code-coverage", "swift test"
    ),
}

_UNKNOWN_SPEC = _RunnerSpec("unknown", "unknown", "", "")


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass
class _LineHit:
    line: int
    hit: int


@dataclass
class _FnHit:
    name: str
    line: int
    hit: int


@dataclass
class _FileCoverage:
    path: str
    lines: list[_LineHit]
    functions: list[_FnHit]
    line_rate: float
    function_rate: float


@dataclass
class _Report:
    files: list[_FileCoverage]
    total_line_rate: float
    total_function_rate: float


@dataclass
class _Gap:
    file_path: str
    uncovered_lines: list[int]
    uncovered_functions: list[str]


@dataclass
class _Env:
    test_runner: str
    language: str
    coverage_command: str
    test_command: str


@dataclass
class _Config:
    test_runner: str | None
    test_command: str | None
    coverage_command: str | None
    coverage_dir: str
    coverage_format: str
    source_dir: list[str]
    threshold: int
    coverage_timeout: float
    ignore: list[str]


class _GitDiffError(Exception):
    """Raised when ``@diff`` cannot resolve a repo/base ref."""


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _truncate(text: str, limit: int = _MAX_OUTPUT_CHARS) -> str:
    """Keep the head AND the tail: runner summaries and failures live at the end."""
    if len(text) <= limit:
        return text
    head = limit // 2
    tail = limit - head
    return text[:head] + "\n\n… [middle truncated] …\n\n" + text[-tail:]


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _read_json(path: Path) -> dict[str, object] | None:
    raw = _read_text(path)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    return {str(k): v for k, v in data.items()}


def _as_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return default
    return default


def _as_float(value: object, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _as_str_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def _pct(block: object) -> float | None:
    if isinstance(block, dict):
        value = block.get("pct")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _env_from_spec(spec: _RunnerSpec) -> _Env:
    return _Env(
        spec.test_runner, spec.language, spec.coverage_command, spec.test_command
    )


def _norm_abs(path: str, base: Path) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = base / p
    return str(p)


def _relative(path: str, root: str) -> str:
    base = root.rstrip("/") + "/"
    return path[len(base):] if path.startswith(base) else path


def _is_within(path: str, directory: Path | None) -> bool:
    if directory is None:
        return True
    norm = str(directory).rstrip("/")
    return path == norm or path.startswith(norm + "/")


def _collapse_ranges(numbers: list[int], limit: int = 20) -> str:
    ordered = sorted(set(numbers))
    parts: list[str] = []
    index = 0
    while index < len(ordered):
        start = ordered[index]
        end = start
        while index + 1 < len(ordered) and ordered[index + 1] == end + 1:
            index += 1
            end = ordered[index]
        parts.append(str(start) if start == end else f"{start}-{end}")
        index += 1
    shown = ", ".join(parts[:limit])
    return shown + ("…" if len(parts) > limit else "")


def _has_project_extension(root: Path, extensions: tuple[str, ...]) -> bool:
    try:
        return any(entry.name.endswith(extensions) for entry in root.iterdir())
    except OSError:
        return False


def _parse_scope(
    scope: str, root: Path
) -> tuple[Path | None, bool, str | None, str | None]:
    """Split a scope string into (dir, want_diff, ref, unknown_path).

    A bare token that is not an existing path is kept as a possible ref (a
    branch name) and returned as ``unknown_path`` too, so the caller can either
    treat it as a base branch or fail loudly. Lacuna errors on a missing path;
    silently scoping to a directory that does not exist is how you get a fake
    "no gaps" answer.
    """
    scope_dir: Path | None = None
    want_diff = False
    ref: str | None = None
    unknown: str | None = None
    for token in scope.split():
        if token == "@diff":
            want_diff = True
        elif token.startswith("@diff:"):
            want_diff = True
            ref = token[len("@diff:"):] or None
        else:
            path = Path(token).expanduser()
            full = path if path.is_absolute() else (root / token)
            if full.exists():
                scope_dir = full.parent if full.is_file() else full
            else:
                unknown = token
    return (scope_dir.resolve() if scope_dir else None), want_diff, ref, unknown


# --------------------------------------------------------------------------- #
# Coverage report parsers (lcov / istanbul / json-summary)
# --------------------------------------------------------------------------- #


def _finish_file(
    path: str, lines: list[_LineHit], functions: list[_FnHit]
) -> _FileCoverage:
    covered_lines = sum(1 for ln in lines if ln.hit > 0)
    covered_fns = sum(1 for fn in functions if fn.hit > 0)
    return _FileCoverage(
        path=path,
        lines=lines,
        functions=functions,
        line_rate=(covered_lines / len(lines)) if lines else 1.0,
        function_rate=(covered_fns / len(functions)) if functions else 1.0,
    )


def _report_from_files(files: list[_FileCoverage]) -> _Report:
    total_lines = sum(len(f.lines) for f in files)
    covered_lines = sum(sum(1 for ln in f.lines if ln.hit > 0) for f in files)
    total_fns = sum(len(f.functions) for f in files)
    covered_fns = sum(sum(1 for fn in f.functions if fn.hit > 0) for f in files)
    return _Report(
        files=files,
        total_line_rate=(covered_lines / total_lines) if total_lines else 1.0,
        total_function_rate=(covered_fns / total_fns) if total_fns else 1.0,
    )


def _parse_lcov(text: str) -> _Report:
    files: list[_FileCoverage] = []
    cur_path: str | None = None
    cur_lines: list[_LineHit] = []
    cur_fns: list[_FnHit] = []
    fn_lines: dict[str, int] = {}

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("SF:"):
            cur_path = line[3:]
            cur_lines = []
            cur_fns = []
            fn_lines = {}
        elif line.startswith("FN:") and cur_path is not None:
            head, _, name = line[3:].partition(",")
            if name:
                try:
                    fn_lines[name] = int(head)
                except ValueError:
                    pass
        elif line.startswith("FNDA:") and cur_path is not None:
            head, _, name = line[5:].partition(",")
            if name:
                try:
                    hit = int(head)
                except ValueError:
                    hit = 0
                cur_fns.append(_FnHit(name, fn_lines.get(name, 0), hit))
        elif line.startswith("DA:") and cur_path is not None:
            head, _, hit_str = line[3:].partition(",")
            if hit_str:
                try:
                    cur_lines.append(_LineHit(int(head), int(hit_str)))
                except ValueError:
                    pass
        elif line == "end_of_record" and cur_path is not None:
            files.append(_finish_file(cur_path, cur_lines, cur_fns))
            cur_path = None

    return _report_from_files(files)


def _parse_istanbul(data: dict[str, object]) -> _Report:
    files: list[_FileCoverage] = []
    for path, entry in data.items():
        if not isinstance(entry, dict):
            continue
        line_hits: dict[int, int] = {}
        stmt_map = entry.get("statementMap")
        stmt_hits = entry.get("s")
        if isinstance(stmt_map, dict) and isinstance(stmt_hits, dict):
            for sid, stmt in stmt_map.items():
                if not isinstance(stmt, dict):
                    continue
                start = stmt.get("start")
                line_no = start.get("line") if isinstance(start, dict) else None
                if not isinstance(line_no, int):
                    continue
                hit = stmt_hits.get(sid, 0)
                hit = hit if isinstance(hit, int) else 0
                line_hits[line_no] = max(line_hits.get(line_no, 0), hit)

        functions: list[_FnHit] = []
        fn_map = entry.get("fnMap")
        fn_hits = entry.get("f")
        if isinstance(fn_map, dict):
            for fid, fn in fn_map.items():
                if not isinstance(fn, dict):
                    continue
                name = fn.get("name")
                decl = fn.get("decl")
                line_no = None
                if isinstance(decl, dict):
                    start = decl.get("start")
                    if isinstance(start, dict):
                        line_no = start.get("line")
                hit = fn_hits.get(fid, 0) if isinstance(fn_hits, dict) else 0
                functions.append(
                    _FnHit(
                        str(name) if name is not None else "anonymous",
                        line_no if isinstance(line_no, int) else 0,
                        hit if isinstance(hit, int) else 0,
                    )
                )

        lines = [_LineHit(ln, line_hits[ln]) for ln in sorted(line_hits)]
        files.append(_finish_file(path, lines, functions))

    return _report_from_files(files)


def _parse_json_summary(data: dict[str, object]) -> _Report:
    files: list[_FileCoverage] = []
    for path, entry in data.items():
        if path == "total" or not isinstance(entry, dict):
            continue
        line_pct = _pct(entry.get("lines"))
        fn_pct = _pct(entry.get("functions"))
        files.append(
            _FileCoverage(
                path,
                [],
                [],
                (line_pct / 100.0) if line_pct is not None else 1.0,
                (fn_pct / 100.0) if fn_pct is not None else 1.0,
            )
        )

    total = data.get("total")
    total_line: float | None = None
    total_fn: float | None = None
    if isinstance(total, dict):
        tp_line = _pct(total.get("lines"))
        tp_fn = _pct(total.get("functions"))
        total_line = tp_line / 100.0 if tp_line is not None else None
        total_fn = tp_fn / 100.0 if tp_fn is not None else None
    if total_line is None:
        total_line = _mean_rate(files, "line")
    if total_fn is None:
        total_fn = _mean_rate(files, "fn")
    return _Report(files, total_line, total_fn)


def _mean_rate(files: list[_FileCoverage], which: str) -> float:
    if not files:
        return 1.0
    if which == "line":
        return sum(f.line_rate for f in files) / len(files)
    return sum(f.function_rate for f in files) / len(files)


def _resolve_lcov_path(coverage_dir: Path) -> Path | None:
    standard = coverage_dir / "lcov.info"
    if standard.is_file():
        return standard
    try:
        candidates = [
            p
            for p in coverage_dir.iterdir()
            if p.is_file() and p.name.endswith(".lcov")
        ]
    except OSError:
        return None
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


# --------------------------------------------------------------------------- #
# Gap filtering (testability, ignores, existing tests)
# --------------------------------------------------------------------------- #

_IGNORE_DIRS = {
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".git",
    ".next",
    ".nuxt",
    "out",
    "vendor",
    "target",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "site-packages",
    "dist-packages",
    ".tox",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "Pods",
    "DerivedData",
    "tmp",
    "temp",
    "fixtures",
    "migrations",
    "seeds",
    "i18n",
    "locales",
    "locale",
    "translations",
}
_IGNORE_FILE_RES = (
    re.compile(r"\.d\.ts$"),
    re.compile(r"\.test\.[^.]+$"),
    re.compile(r"\.spec\.[^.]+$"),
    re.compile(r"\.stories\.[^.]+$"),
    re.compile(r"\.config\.[^.]+$"),
    re.compile(r"\.mock\.[^.]+$"),
    re.compile(r"\.fixture\.[^.]+$"),
    re.compile(r"\.enum\.[^.]+$"),
    re.compile(r"\.types?\.[^.]+$"),
    re.compile(r"\.constants?\.[^.]+$"),
    re.compile(r"\.interface\.[^.]+$"),
)


def _should_ignore(abs_path: str, user_ignore: list[str]) -> bool:
    for part in Path(abs_path).parts:
        if part.lower() in _IGNORE_DIRS:
            return True
    if any(rx.search(abs_path) for rx in _IGNORE_FILE_RES):
        return True
    return any(pattern in abs_path for pattern in user_ignore)


def _strip_code_noise(source: str) -> str:
    stripped = re.sub(r"//[^\n]*", "", source)
    stripped = re.sub(r"/\*[\s\S]*?\*/", "", stripped)
    stripped = re.sub(r"'(?:[^'\\]|\\.)*'", '""', stripped)
    stripped = re.sub(r'"(?:[^"\\]|\\.)*"', '""', stripped)
    return re.sub(r"`(?:[^`\\]|\\.)*`", '""', stripped)


def _has_testable_code(source: str) -> bool:
    stripped = _strip_code_noise(source)
    checks = (
        r"\bfunction\s*[\w(]",
        r"=>\s*\{",
        r"\bclass\s+\w",
        r"\bexport\s+(?:default\s+)?const\s+[\w$]+[^\n]*=>",
        r"\b(?:async\s+)?[\w$]+\s*\([^)]*\)\s*(?::[^={]+)?\{",
        r"^\s*(?:async\s+)?def\s+\w+",
        r"^\s*func\s+\w+",
    )
    return any(re.search(rx, stripped, re.MULTILINE) for rx in checks)


def _test_file_exists(abs_source: str) -> bool:
    path = Path(abs_source)
    directory = path.parent
    ext = path.suffix
    base = path.stem
    for candidate in (
        directory / "__tests__" / f"{base}.test{ext}",
        directory / "__tests__" / f"{base}.spec{ext}",
        directory / f"{base}.test{ext}",
        directory / f"{base}.spec{ext}",
        directory / f"test_{base}{ext}",
        directory / f"{base}_test{ext}",
    ):
        if candidate.is_file():
            return True
    return False


def _walk_sources(directory: Path) -> list[Path]:
    out: list[Path] = []
    try:
        entries = list(directory.iterdir())
    except OSError:
        return out
    for entry in entries:
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            if entry.name.lower() not in _IGNORE_DIRS:
                out.extend(_walk_sources(entry))
        elif entry.suffix in _SOURCE_EXTENSIONS:
            out.append(entry)
    return out


def _is_test_file(path: Path) -> bool:
    return bool(_TEST_FILE_RE.search(path.name))


def _parse_pass_count(output: str) -> int:
    """Passing tests per the runner footer; 0 when nothing was collected.

    Ported from lacuna's ``parsePassCount``. Never reads the vitest
    "Test Files 1 passed" line, which would make a 15-test run look like 1.
    """
    clean = re.sub(r"\x1b\[[0-9;]*m", "", output)
    summary = re.search(r"^\s*Tests\b[^\n]*?(\d+)\s+passed", clean, re.MULTILINE)
    if summary:
        return int(summary.group(1))
    for line in clean.splitlines():
        if re.search(r"Test\s+Files", line, re.IGNORECASE):
            continue
        match = re.search(r"(\d+)\s+passed", line)
        if match:
            return int(match.group(1))
    return 0


def _align_report_to_changed(
    report: _Report, changed: dict[str, set[int]], base: Path
) -> _Report:
    """Realign package-relative report paths onto absolute git-diff paths.

    A vitest workspace reports ``src/foo.ts`` for a package at
    ``packages/api`` while ``git diff`` yields the repo-root absolute path. Left
    alone, the same file keys two ways and every changed line looks uncovered
    (a spurious 0%). Only rewrites on a single unambiguous suffix match.
    """
    changed_abs = [p.replace("\\", "/") for p in changed]
    changed_set = set(changed_abs)
    touched = False
    files: list[_FileCoverage] = []
    for file in report.files:
        abs_path = _norm_abs(file.path, base).replace("\\", "/")
        if abs_path in changed_set:
            # Matches already; still rewrite so a package-relative path is
            # keyed absolutely everywhere downstream.
            touched = touched or file.path != abs_path
            files.append(
                _FileCoverage(
                    abs_path,
                    file.lines,
                    file.functions,
                    file.line_rate,
                    file.function_rate,
                )
            )
            continue
        rel = file.path.replace("\\", "/").lstrip("./")
        matches = [c for c in changed_abs if c.endswith("/" + rel)]
        if len(matches) == 1:
            touched = True
            files.append(
                _FileCoverage(
                    matches[0],
                    file.lines,
                    file.functions,
                    file.line_rate,
                    file.function_rate,
                )
            )
        else:
            files.append(file)
    if not touched:
        return report
    return _Report(files, report.total_line_rate, report.total_function_rate)


# --------------------------------------------------------------------------- #
# Unified-diff parsing (changed new-side lines)
# --------------------------------------------------------------------------- #


def _parse_unified_diff(text: str, repo_root: str) -> dict[str, set[int]]:
    changed: dict[str, set[int]] = {}
    current: set[int] | None = None
    for line in text.splitlines():
        if line.startswith("+++ "):
            p = line[4:].strip()
            if p == "/dev/null":
                current = None
                continue
            if p.startswith('"') and p.endswith('"'):
                p = p[1:-1]
            if p.startswith("b/"):
                p = p[2:]
            if not _SOURCE_EXT_RE.search(p):
                current = None
                continue
            abs_path = p if p.startswith("/") else str(Path(repo_root) / p)
            current = changed.setdefault(abs_path, set())
            continue
        if current is not None and line.startswith("@@"):
            match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            if not match:
                continue
            start = int(match.group(1))
            count = int(match.group(2)) if match.group(2) is not None else 1
            for offset in range(count):
                current.add(start + offset)
    return {p: lines for p, lines in changed.items() if lines}


# --------------------------------------------------------------------------- #
# Toolkit
# --------------------------------------------------------------------------- #


class TestRunnerToolkit(BaseToolkit, AbstractToolkit):
    """Deterministic coverage-gap + diff analysis; no CLI, no model."""

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
                "working_directory is required for TestRunnerToolkit; coverage "
                "runs within the task's project directory."
            )
        self.working_directory = str(Path(working_directory).expanduser().resolve())

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _skill_md_path(self) -> Path | None:
        """Locate the lacuna-cli skill's SKILL.md across known layouts."""
        candidates: list[Path] = []
        override = env("UNDISCLOSED_SKILLS_DIR", "")
        if override:
            candidates.append(Path(override) / _SKILL_NAME / "SKILL.md")
        home_skills = Path.home() / ".undisclosed"
        candidates.append(home_skills / "skills" / _SKILL_NAME / "SKILL.md")
        candidates.extend(
            sorted(home_skills.glob(f"user_*/skills/{_SKILL_NAME}/SKILL.md"))
        )
        candidates.append(
            Path(self.working_directory)
            / ".undisclosed"
            / "skills"
            / _SKILL_NAME
            / "SKILL.md"
        )
        for path in candidates:
            if path.is_file():
                return path
        return None

    def _load_config(self) -> _Config:
        root = Path(self.working_directory)
        raw: dict[str, object] = {}
        found = False
        for name in (".lacuna.json", ".lacunarc.json", ".lacunarc"):
            data = _read_json(root / name)
            if data is not None:
                raw = data
                found = True
                break
        if not found:
            pkg = _read_json(root / "package.json")
            if isinstance(pkg, dict) and isinstance(pkg.get("lacuna"), dict):
                lacuna = pkg["lacuna"]
                if isinstance(lacuna, dict):
                    raw = {str(k): v for k, v in lacuna.items()}

        return _Config(
            test_runner=_as_str(raw.get("testRunner")),
            test_command=_as_str(raw.get("testCommand")),
            coverage_command=_as_str(raw.get("coverageCommand")),
            coverage_dir=_as_str(raw.get("coverageDir")) or "coverage",
            coverage_format=_as_str(raw.get("coverageFormat")) or "lcov",
            source_dir=_as_str_list(raw.get("sourceDir")) or ["src"],
            threshold=_as_int(raw.get("threshold"), _DEFAULT_THRESHOLD),
            coverage_timeout=_as_float(raw.get("coverageTimeout"), 300.0),
            ignore=_as_str_list(raw.get("ignore")),
        )

    def _detect_env(self, config: _Config) -> _Env:
        root = Path(self.working_directory)
        if config.test_runner and config.test_runner in _RUNNERS:
            spec = _RUNNERS[config.test_runner]
            return _Env(
                spec.test_runner,
                spec.language,
                self._localize(
                    config.coverage_command or spec.coverage_command, root
                ),
                self._localize(config.test_command or spec.test_command, root),
            )

        pkg = _read_json(root / "package.json")
        deps: dict[str, object] = {}
        if isinstance(pkg, dict):
            for key in ("dependencies", "devDependencies"):
                block = pkg.get(key)
                if isinstance(block, dict):
                    deps.update(block)

        detected: _RunnerSpec | None = None
        if "vitest" in deps:
            detected = _RUNNERS["vitest"]
        elif "jest" in deps or "@jest/core" in deps:
            detected = _RUNNERS["jest"]
        elif "mocha" in deps:
            detected = _RUNNERS["mocha"]
        elif (root / "pytest.ini").is_file() or (root / "pyproject.toml").is_file():
            detected = _RUNNERS["pytest"]
        elif (root / "go.mod").is_file():
            detected = _RUNNERS["go-test"]
        elif (root / "Cargo.toml").is_file():
            detected = _RUNNERS["cargo-test"]
        else:
            detected = self._detect_non_node(root)

        if detected is None:
            return _env_from_spec(_UNKNOWN_SPEC)
        return _Env(
            detected.test_runner,
            detected.language,
            self._localize(
                config.coverage_command or detected.coverage_command, root
            ),
            self._localize(config.test_command or detected.test_command, root),
        )

    def governance_command(self) -> str:
        """The coverage command `run_tests` and `coverage_gap_plan` execute."""
        config = self._load_config()
        return self._detect_env(config).coverage_command or ""

    def _localize(self, command: str, root: Path) -> str:
        """Use the project's venv python for Python runners when one exists."""
        if not command.startswith(("python ", "python3 ")):
            return command
        for candidate in (root / ".venv/bin/python", root / "venv/bin/python"):
            if candidate.is_file():
                return command.replace("python3 ", f"{candidate} ", 1).replace(
                    "python ", f"{candidate} ", 1
                )
        return command

    def _detect_non_node(self, root: Path) -> _RunnerSpec | None:
        gemfile = _read_text(root / "Gemfile")
        if gemfile is not None and re.search(r"\brspec\b", gemfile):
            return _RUNNERS["rspec"]
        composer = _read_json(root / "composer.json")
        if isinstance(composer, dict):
            cdeps: dict[str, object] = {}
            for key in ("require", "require-dev"):
                block = composer.get(key)
                if isinstance(block, dict):
                    cdeps.update(block)
            return _RUNNERS["pest"] if "pestphp/pest" in cdeps else _RUNNERS["phpunit"]
        if (root / "Directory.Build.props").is_file() or _has_project_extension(
            root, (".csproj", ".sln")
        ):
            return _RUNNERS["dotnet-test"]
        if (root / "build.gradle").is_file() or (root / "build.gradle.kts").is_file():
            return _RUNNERS["gradle-test"]
        if (root / "pom.xml").is_file():
            return _RUNNERS["maven-test"]
        if (root / "Package.swift").is_file():
            return _RUNNERS["swift-test"]
        return None

    def _git(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", self.working_directory, *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )

    def _ref_exists(self, ref: str) -> bool:
        return self._git(["rev-parse", "--verify", "--quiet", ref]).returncode == 0

    def _resolve_base_ref(self, explicit: str | None) -> str:
        if explicit:
            if not _SAFE_REF_RE.fullmatch(explicit):
                raise _GitDiffError(f'"{explicit}" is not a valid git ref.')
            if not self._ref_exists(explicit):
                raise _GitDiffError(
                    f'Base ref "{explicit}" could not be resolved. Fetch it '
                    f"first: git fetch origin {explicit.replace('origin/', '')}"
                )
            return explicit
        # Default is main, per the product contract: patch coverage is measured
        # against the mainline unless the user names another branch.
        for candidate in ("origin/main", "main"):
            if self._ref_exists(candidate):
                return candidate
        head = self._git(["rev-parse", "--abbrev-ref", "origin/HEAD"])
        head_ref = head.stdout.strip()
        if head.returncode == 0 and head_ref and head_ref != "origin/HEAD":
            return head_ref
        if self._ref_exists("master"):
            return "master"
        if self._ref_exists("HEAD~1"):
            return "HEAD~1"
        raise _GitDiffError(
            "Could not resolve a base branch for patch coverage: no origin/main, "
            "no main/master, and no parent commit. Fetch the branch "
            "(git fetch origin main) or pass one explicitly, e.g. "
            "coverage_gap_plan(base='develop')."
        )

    def _resolve_diff(
        self, explicit: str | None
    ) -> tuple[str, dict[str, set[int]]]:
        inside = self._git(["rev-parse", "--is-inside-work-tree"])
        if inside.returncode != 0:
            raise _GitDiffError(
                "@diff needs a git repository (this directory is not one, or "
                "git is not installed)."
            )
        top = self._git(["rev-parse", "--show-toplevel"])
        repo_root = (
            top.stdout.strip()
            if top.returncode == 0 and top.stdout.strip()
            else self.working_directory
        )
        base_ref = self._resolve_base_ref(explicit)
        merge_base = self._git(["merge-base", base_ref, "HEAD"])
        if merge_base.returncode != 0 or not merge_base.stdout.strip():
            raise _GitDiffError(
                f"Could not compute a merge-base between {base_ref} and HEAD. "
                "In a shallow clone, fetch history first: git fetch --unshallow"
            )
        diff = self._git(
            [
                "diff",
                "--unified=0",
                "--no-color",
                "--diff-filter=d",
                merge_base.stdout.strip(),
            ]
        )
        changed = _parse_unified_diff(diff.stdout, repo_root) if diff.stdout else {}
        # `git diff` never reports untracked files, and a brand-new source file
        # is exactly what patch coverage must judge. Treat every line of an
        # untracked (non-ignored) source file as changed.
        for path, lines in self._untracked_lines(repo_root).items():
            changed.setdefault(path, set()).update(lines)
        return base_ref, changed

    def _untracked_lines(self, repo_root: str) -> dict[str, set[int]]:
        listed = self._git(
            ["ls-files", "--others", "--exclude-standard", "--full-name"]
        )
        if listed.returncode != 0:
            return {}
        root = Path(repo_root)
        out: dict[str, set[int]] = {}
        for rel in listed.stdout.splitlines():
            rel = rel.strip()
            if not rel or not _SOURCE_EXT_RE.search(rel):
                continue
            path = root / rel
            text = _read_text(path)
            if text is None:
                continue
            out[str(path)] = set(range(1, len(text.splitlines()) + 1))
        return out

    def _run_command(self, command: str, timeout: float) -> tuple[bool, str]:
        """Run a shell command in the project dir; return (ok, output)."""
        try:
            proc = subprocess.run(
                command,
                cwd=self.working_directory,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False, f"[timed out after {timeout:g}s]"
        except Exception as exc:  # pragma: no cover - defensive
            return False, f"[failed to run: {exc}]"
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return proc.returncode == 0, output

    def _load_report(self, config: _Config) -> _Report | None:
        coverage_dir = Path(self.working_directory) / config.coverage_dir
        if config.coverage_format == "json-summary":
            data = _read_json(coverage_dir / "coverage-summary.json")
            return _parse_json_summary(data) if data is not None else None
        lcov_path = _resolve_lcov_path(coverage_dir)
        if lcov_path is not None:
            text = _read_text(lcov_path)
            if text is not None:
                return _parse_lcov(text)
        final = _read_json(coverage_dir / "coverage-final.json")
        if final is not None:
            return _parse_istanbul(final)
        return None

    def _filter_testable(
        self, gaps: list[_Gap], include_existing: bool, ignore: list[str]
    ) -> list[_Gap]:
        root = Path(self.working_directory)
        out: list[_Gap] = []
        for gap in gaps:
            abs_path = _norm_abs(gap.file_path, root)
            if _should_ignore(abs_path, ignore):
                continue
            if not include_existing and _test_file_exists(abs_path):
                continue
            source = _read_text(Path(abs_path))
            if source is not None and _has_testable_code(source):
                out.append(gap)
        return out

    def _extract_gaps(self, report: _Report, threshold: int) -> list[_Gap]:
        root = Path(self.working_directory)
        gaps: list[_Gap] = []
        for file in report.files:
            if file.line_rate * 100 >= threshold:
                continue
            uncovered_lines = [ln.line for ln in file.lines if ln.hit == 0]
            uncovered_fns = [fn.name for fn in file.functions if fn.hit == 0]
            if not uncovered_lines and not uncovered_fns:
                continue
            gaps.append(
                _Gap(_norm_abs(file.path, root), uncovered_lines, uncovered_fns)
            )
        return gaps

    def _find_test_files(self, scope_dir: Path | None = None) -> list[Path]:
        root = Path(self.working_directory)
        search = [scope_dir] if scope_dir is not None else [root]
        found: list[Path] = []
        seen: set[str] = set()
        for directory in search:
            for path in _walk_sources(directory):
                key = str(path)
                if key in seen:
                    continue
                seen.add(key)
                if _is_test_file(path):
                    found.append(path)
        return found

    def _find_untouched(
        self, report: _Report, config: _Config, scope_dir: Path | None
    ) -> list[_Gap]:
        root = Path(self.working_directory)
        report_paths = {_norm_abs(f.path, root) for f in report.files}
        if scope_dir is not None:
            search_dirs = [scope_dir]
        else:
            # A configured source dir that does not exist (the default "src" in
            # a Python/Go repo) would silently find nothing; fall back to root.
            configured = [root / d for d in config.source_dir]
            search_dirs = [d for d in configured if d.is_dir()] or [root]
        candidates: list[_Gap] = []
        for directory in search_dirs:
            for path in _walk_sources(directory):
                if str(path) not in report_paths:
                    candidates.append(_Gap(str(path), [], []))
        return self._filter_testable(candidates, include_existing=False, ignore=config.ignore)

    # ------------------------------------------------------------------ #
    # Tools
    # ------------------------------------------------------------------ #

    def read_test_skill(self) -> str:
        """Return the lacuna-cli skill guidance (its SKILL.md).

        Use this when the user wants the full lacuna CLI (generate/fix tests) --
        that AI loop lives in the skill, not in this toolkit. This toolkit only
        reports coverage gaps + the diff check.

        Returns:
            str: The SKILL.md content, or a message if it can't be located.
        """
        path = self._skill_md_path()
        if not path:
            return (
                "[skill not found]: could not locate the lacuna-cli SKILL.md. "
                "Expected under ~/.undisclosed/skills/lacuna-cli/SKILL.md."
            )
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover - defensive
            return f"[skill read error]: {exc}"
        return _truncate(text)

    def coverage_gap_plan(
        self, scope: str = "", threshold: int = 0, base: str = ""
    ) -> str:
        """Report coverage gaps (read-only); defaults to the changed-lines lens.

        Detects the project's test runner, runs the suite WITH coverage, parses
        the coverage report, and lists the uncovered files/lines/functions. Runs
        no model and needs no `lacuna` install.

        The default scope is the Codecov-style diff lens against ``main``: the
        plan reports the *changed* lines that are uncovered (and the patch
        coverage of the changed files), matching how a PR coverage gate judges
        a patch. Falls back to a whole-repo analysis when no base branch exists.

        Args:
            scope (str): '' (defaults to the changed-lines lens), a path to
                narrow to, or '@diff[:<ref>]' (optionally with a path, e.g.
                '@diff:develop packages/api').
            threshold (int): Minimum line-coverage % for whole-repo mode
                (defaults to the project's configured threshold, else 80).
                Diff mode ignores it and keeps every changed file with any
                uncovered line, like a patch gate.
            base (str): Branch/ref to diff against instead of ``main``
                (e.g. 'origin/develop'). Only used by the diff lens.

        Returns:
            str: A coverage-gap plan, or a clear error message.
        """
        return self._run_and_plan(scope, threshold, include_output=False, base=base)

    def run_tests(self, scope: str = "", base: str = "") -> str:
        """Run the suite with coverage and pair it with the gap plan.

        Runs the detected coverage command (which executes the tests) and
        returns its output together with the coverage-gap plan, so a run always
        surfaces what it does not cover. The output starts with the exact
        command (the UI reads it for the test receipt) and ends with the suite
        output, summary included.

        Args:
            scope (str): Coverage scope for the gap plan (see
                `coverage_gap_plan`); default is the changed-lines lens.
            base (str): Branch/ref to diff against instead of ``main``.

        Returns:
            str: The suite output plus the coverage-gap plan.
        """
        return self._run_and_plan(scope, 0, include_output=True, base=base)

    # ------------------------------------------------------------------ #
    # Core
    # ------------------------------------------------------------------ #

    def _run_and_plan(
        self, scope: str, threshold: int, include_output: bool, base: str = ""
    ) -> str:
        config = self._load_config()
        env_ = self._detect_env(config)
        if env_.test_runner == "unknown" or not env_.coverage_command:
            return (
                "[coverage error]: could not detect a test runner/coverage "
                "command for this project. Set `testRunner` (and/or "
                "`coverageCommand`) in .lacuna.json. Known runners: "
                + ", ".join(sorted(_RUNNERS))
                + "."
            )

        root = Path(self.working_directory)
        explicit = bool(scope.strip() or base.strip())
        requested = scope.strip()
        if not requested:
            requested = f"@diff:{base.strip()}" if base.strip() else "@diff"
        scope_dir, want_diff, ref, unknown = _parse_scope(requested, root)

        if unknown:
            if not want_diff and self._ref_exists(unknown):
                # `coverage_gap_plan(scope="develop")` -- a branch, not a path.
                want_diff, ref = True, unknown
            else:
                return (
                    f"[coverage error]: path not found: {unknown}. Pass an "
                    "existing directory, or a base branch via base='...'."
                )

        threshold = threshold if threshold else config.threshold

        # Resolve the diff before running anything: a docs-only diff is free.
        patch: tuple[float, int, int] | None = None
        base_ref: str | None = None
        changed: dict[str, set[int]] = {}
        diff_active = False
        if want_diff:
            try:
                base_ref, changed = self._resolve_diff(ref)
            except _GitDiffError as exc:
                if explicit:
                    return f"[coverage error]: {exc}"
                # Default branch unavailable -> whole-repo analysis.
                changed = {}
            else:
                if scope_dir is not None:
                    changed = {
                        path: lines
                        for path, lines in changed.items()
                        if _is_within(path, scope_dir)
                    }
                diff_active = True

        if diff_active and not changed:
            return "\n".join(
                [
                    "COVERAGE-GAP PLAN (read-only, no model, no lacuna CLI)",
                    f"Detected:   {env_.test_runner} ({env_.language})",
                    f"Scope:      changed lines vs {base_ref}",
                    f"No changed source files in the diff vs {base_ref} -- "
                    "nothing to cover.",
                ]
            )

        has_tests = bool(self._find_test_files(scope_dir))
        ok = True
        output = ""
        report: _Report | None = None
        if has_tests:
            ok, output = self._run_command(
                env_.coverage_command, config.coverage_timeout
            )
            report = self._load_report(config)
            if report is None:
                if not ok:
                    missing = re.search(
                        r"unrecognized arguments:.*--cov|"
                        r"No module named '?(?:pytest_cov|coverage)'?",
                        output,
                        re.IGNORECASE,
                    )
                    if missing:
                        return (
                            "[coverage error]: the coverage plugin is missing "
                            f"({missing.group(0)}). Install it "
                            "(`python -m pip install pytest-cov`) or set "
                            "`coverageCommand` in .lacuna.json to the project's "
                            "own coverage script."
                        )
                    return (
                        "[coverage error]: the coverage command failed and no "
                        f"coverage report was found under '{config.coverage_dir}/'."
                        "\n\n" + _truncate(output[-_FAILURE_TAIL_CHARS:])
                    )
                return (
                    "[coverage error]: the coverage command succeeded but no report "
                    f"(lcov.info / *.lcov / coverage-final.json / "
                    f"coverage-summary.json) was found under "
                    f"'{config.coverage_dir}/'. Check the runner's coverage "
                    "reporter config and `coverageDir`/`coverageFormat`."
                )
            # A run that collected zero passing tests measured nothing; every
            # changed line would look uncovered. That phantom 0% is the classic
            # monorepo trap (root command skips a package's prerequisites).
            zero_evidence = bool(
                re.search(
                    r"no tests ran|No test files found|No tests found|"
                    r"collected 0 items|Tests:\s+0 total|Executed 0 tests",
                    output,
                    re.IGNORECASE,
                )
            )
            countable = env_.test_runner in {
                "vitest",
                "jest",
                "pytest",
                "cargo-test",
                "mocha",
            }
            failed_any = bool(re.search(r"\d+\s+(?:failed|error)", output))
            zero_tests = zero_evidence or (
                countable
                and ok
                and not failed_any
                and _parse_pass_count(output) == 0
            )
            if diff_active and zero_tests:
                abort = re.search(
                    r"Unhandled Error|Configuration property .*? is not defined|"
                    r"globalSetup\b|No test files found|Cannot find (?:module|package)",
                    output,
                )
                hint = (
                    f'\nThe suite aborted before running: "{abort.group(0)}".'
                    if abort
                    else ""
                )
                return (
                    "[coverage error]: the suite executed 0 tests, so patch "
                    f"coverage vs {base_ref} would be a phantom 0%.{hint}\n"
                    "In a monorepo the root coverage command often skips a "
                    "package's build step or config/env and exits with an empty "
                    "report. Run it the way the package's `test:cov` script does, "
                    "or point `coverageDir` at that package's report."
                )
        else:
            report = _Report([], 0.0, 0.0)

        if diff_active:
            # Reports in a monorepo often key files package-relative; realign
            # them onto the absolute git-diff paths before comparing.
            report = _align_report_to_changed(report, changed, root)
        elif scope_dir is not None:
            report = _Report(
                [
                    f
                    for f in report.files
                    if _is_within(_norm_abs(f.path, root), scope_dir)
                ],
                report.total_line_rate,
                report.total_function_rate,
            )

        # Diff mode keeps every file with ANY uncovered line (threshold 101)
        # and keeps files that already have tests: a 94%-covered file can still
        # have uncovered CHANGED lines. The per-file threshold is whole-repo only.
        gap_threshold = 101 if diff_active else threshold
        include_existing = diff_active or scope_dir is not None
        gaps = self._filter_testable(
            self._extract_gaps(report, gap_threshold), include_existing, config.ignore
        )
        untouched = self._find_untouched(report, config, scope_dir)

        if diff_active:
            gaps, assume_uncovered = self._narrow_to_diff(
                gaps, changed, report, config.ignore
            )
            untouched = []
            patch = self._patch_coverage(report, changed, assume_uncovered)

        scope_label = "whole project"
        if diff_active:
            scope_label = (
                f"changed lines vs {base_ref} ({len(changed)} file(s), "
                f"{sum(len(v) for v in changed.values())} line(s))"
            )
        elif scope_dir is not None:
            scope_label = _relative(str(scope_dir), self.working_directory)

        header = [
            "COVERAGE-GAP PLAN (read-only, no model, no lacuna CLI)",
            f"Detected:   {env_.test_runner} ({env_.language})",
            f"Command:    {env_.coverage_command}",
            f"Scope:      {scope_label}",
            f"Threshold:  {threshold}%",
            f"Coverage:   lines {report.total_line_rate * 100:.1f}% | "
            f"functions {report.total_function_rate * 100:.1f}%",
            (
                f"Suite:      {'passed' if ok else 'FAILED'}"
                if has_tests
                else "Suite:      not run (no test files yet)"
            ),
        ]
        if patch is not None:
            pct, covered, total = patch
            header.append(
                f"Patch:      {pct:.1f}% ({covered}/{total} changed executable lines)"
            )
        if not ok and output:
            header.append("Suite tail: " + output[-_FAILURE_TAIL_CHARS:].strip())

        parts = ["\n".join(header)]
        details = (
            self._changed_file_details(
                report, changed, assume_uncovered if diff_active else set(), root
            )
            if diff_active
            else []
        )
        if details:
            parts.append("Changed files:\n" + "\n".join(details))
        parts.append(self._render_gaps(gaps, untouched, root))
        text = "\n\n".join(parts)
        if include_output:
            text += f"\n\nSuite output:\n{_truncate(output)}"
        return text

    def _narrow_to_diff(
        self,
        gaps: list[_Gap],
        changed: dict[str, set[int]],
        report: _Report,
        ignore: list[str],
    ) -> tuple[list[_Gap], set[str]]:
        root = Path(self.working_directory)
        report_paths = {_norm_abs(f.path, root) for f in report.files}
        gap_paths = {_norm_abs(g.file_path, root) for g in gaps}

        # Changed testable files with no coverage record still count (their tests
        # never ran) -- surface them as whole-file gaps and treat every changed
        # line as uncovered for patch coverage.
        missing = [
            _Gap(abs_path, [], [])
            for abs_path in changed
            if abs_path not in report_paths and abs_path not in gap_paths
        ]
        missing_testable = self._filter_testable(missing, True, ignore)
        assume_uncovered = {
            _norm_abs(g.file_path, root) for g in missing_testable
        }
        gaps = gaps + missing_testable

        narrowed: list[_Gap] = []
        for gap in gaps:
            abs_path = _norm_abs(gap.file_path, root)
            changed_lines = changed.get(abs_path)
            if not changed_lines:
                continue
            if abs_path in report_paths:
                lines = [ln for ln in gap.uncovered_lines if ln in changed_lines]
                if not lines:
                    continue
                narrowed.append(
                    _Gap(abs_path, sorted(lines), gap.uncovered_functions)
                )
            else:
                narrowed.append(_Gap(abs_path, sorted(changed_lines), []))
        return narrowed, assume_uncovered

    def _patch_coverage(
        self,
        report: _Report,
        changed: dict[str, set[int]],
        assume_uncovered: set[str],
    ) -> tuple[float, int, int]:
        """Codecov-style patch coverage: covered/total changed executable lines."""
        root = Path(self.working_directory)
        hits = {
            _norm_abs(f.path, root): {ln.line: ln.hit for ln in f.lines}
            for f in report.files
        }
        covered = 0
        total = 0
        for abs_path, lines in changed.items():
            file_hits = hits.get(abs_path)
            if file_hits is None:
                # Not instrumented: count only changed testable files whose tests
                # never ran (Codecov "assume uncovered"), every line uncovered.
                if abs_path in assume_uncovered:
                    total += len(lines)
                continue
            for line in lines:
                hit = file_hits.get(line)
                if hit is None:
                    continue
                total += 1
                if hit > 0:
                    covered += 1
        return (100.0 if total == 0 else (covered / total) * 100.0), covered, total

    def _changed_file_details(
        self,
        report: _Report,
        changed: dict[str, set[int]],
        assume_uncovered: set[str],
        root: Path,
    ) -> list[str]:
        """One line per changed file: whole-file line rate + changed-line patch."""
        hits = {
            _norm_abs(f.path, root): (f.line_rate, {ln.line: ln.hit for ln in f.lines})
            for f in report.files
        }
        lines: list[str] = []
        for abs_path in sorted(changed):
            changed_lines = changed[abs_path]
            rel = _relative(abs_path, str(root))
            entry = hits.get(abs_path)
            if entry is None:
                if abs_path in assume_uncovered:
                    lines.append(
                        f"  {rel}: no coverage record ({len(changed_lines)} "
                        "changed line(s) uncovered)"
                    )
                else:
                    lines.append(
                        f"  {rel}: not counted (no testable code to instrument)"
                    )
                continue
            line_rate, file_hits = entry
            covered = sum(
                1 for ln in changed_lines if file_hits.get(ln, 0) > 0
            )
            executable = sum(1 for ln in changed_lines if ln in file_hits)
            lines.append(
                f"  {rel}: {line_rate * 100:.1f}% lines | patch "
                f"{covered}/{executable}"
            )
            if len(lines) >= 20:
                remaining = len(changed) - 20
                if remaining > 0:
                    lines.append(f"  … and {remaining} more changed file(s)")
                break
        return lines

    def _render_gaps(
        self,
        gaps: list[_Gap],
        untouched: list[_Gap],
        root: Path,
    ) -> str:
        lines: list[str] = []
        if not gaps and not untouched:
            lines.append("No coverage gaps found. Nothing uncovered in scope.")
            return "\n".join(lines)

        if gaps:
            lines.append(f"Gaps ({len(gaps)}):")
            for gap in gaps:
                rel = _relative(gap.file_path, str(root))
                if gap.uncovered_lines:
                    target = "lines " + _collapse_ranges(gap.uncovered_lines)
                else:
                    target = "whole file (no coverage record)"
                if gap.uncovered_functions:
                    target += "; fns " + ", ".join(gap.uncovered_functions[:10])
                lines.append(f"  {rel}: {target}")

        if untouched:
            lines.append(f"Untouched source files ({len(untouched)}):")
            for gap in untouched:
                lines.append(f"  {_relative(gap.file_path, str(root))}")

        lines.append("")
        lines.append(
            "Review these gaps and state how you will close them before "
            "finishing; call out anything you are deliberately leaving out of "
            "scope."
        )
        return "\n".join(lines)

    def get_tools(self) -> list[FunctionTool]:
        return [
            FunctionTool(self.read_test_skill),
            FunctionTool(self.coverage_gap_plan),
            FunctionTool(self.run_tests),
        ]
