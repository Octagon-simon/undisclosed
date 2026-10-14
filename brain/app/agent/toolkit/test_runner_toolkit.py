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
  - ``coverage_gap_plan`` -- the gap plan (defaults to the changed-lines lens,
                             ``@diff:origin/main``, like a patch-coverage gate).
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
#: File modes that can carry patch coverage (docs/config/lockfiles excluded).
_SOURCE_EXT_RE = re.compile(r"\.(?:ts|tsx|js|jsx|mts|cts|mjs|cjs)$")
#: Refs are interpolated into a git command -- allow only ref-shaped strings.
_SAFE_REF_RE = re.compile(r"[\w\-./@~^{}]+")
_JS_SOURCE_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mts", ".cts"}


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
    if len(text) <= limit:
        return text
    return text[:limit] + "\n… [output truncated]"


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


def _parse_scope(scope: str, root: Path) -> tuple[Path | None, bool, str | None]:
    """Split a scope string into (dir, want_diff, ref)."""
    scope_dir: Path | None = None
    want_diff = False
    ref: str | None = None
    for token in scope.split():
        if token == "@diff":
            want_diff = True
        elif token.startswith("@diff:"):
            want_diff = True
            ref = token[len("@diff:"):] or None
        else:
            path = Path(token)
            full = path if path.is_absolute() else (root / token)
            scope_dir = full.parent if full.is_file() else full
    return scope_dir, want_diff, ref


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
        elif entry.suffix in _JS_SOURCE_EXTENSIONS:
            out.append(entry)
    return out


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
        self.working_directory = str(Path(working_directory).expanduser())

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
        if config.test_runner and config.test_runner in _RUNNERS:
            spec = _RUNNERS[config.test_runner]
            return _Env(
                spec.test_runner,
                spec.language,
                config.coverage_command or spec.coverage_command,
                config.test_command or spec.test_command,
            )

        root = Path(self.working_directory)
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
            config.coverage_command or detected.coverage_command,
            config.test_command or detected.test_command,
        )

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
        head = self._git(["rev-parse", "--abbrev-ref", "origin/HEAD"])
        head_ref = head.stdout.strip()
        if head.returncode == 0 and head_ref and head_ref != "origin/HEAD":
            return head_ref
        for candidate in ("main", "master"):
            if self._ref_exists(f"refs/heads/{candidate}"):
                return candidate
        if self._ref_exists("HEAD~1"):
            return "HEAD~1"
        raise _GitDiffError(
            "Could not resolve a base ref for @diff: no origin/HEAD, no local "
            "main/master, and no parent commit. Pass one explicitly, e.g. "
            "'@diff:origin/main'."
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
        return base_ref, changed

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

    def _find_untouched(
        self, report: _Report, config: _Config, scope_dir: Path | None
    ) -> list[_Gap]:
        root = Path(self.working_directory)
        report_paths = {_norm_abs(f.path, root) for f in report.files}
        search_dirs = (
            [scope_dir]
            if scope_dir is not None
            else [root / d for d in config.source_dir]
        )
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

    def coverage_gap_plan(self, scope: str = "", threshold: int = 0) -> str:
        """Report coverage gaps (read-only); defaults to the changed-lines lens.

        Detects the project's test runner, runs the suite WITH coverage, parses
        the coverage report, and lists the uncovered files/lines/functions. Runs
        no model and needs no `lacuna` install.

        The default scope is the Codecov-style diff lens (``@diff:origin/main``),
        so the plan reports the *changed* lines that are uncovered, matching how
        a PR coverage gate judges a patch. Falls back to a whole-repo analysis
        when no base ref is available.

        Args:
            scope (str): '' (defaults to @diff:origin/main), a path to narrow to,
                or '@diff[:<ref>]' (optionally with a path, e.g.
                '@diff:origin/main packages/api').
            threshold (int): Minimum line-coverage % (defaults to the project's
                configured threshold, else 80).

        Returns:
            str: A coverage-gap plan, or a clear error message.
        """
        return self._run_and_plan(scope, threshold, include_output=False)

    def run_tests(self, scope: str = "") -> str:
        """Run the suite with coverage and pair it with the gap plan.

        Runs the detected coverage command (which executes the tests) and
        returns its output together with the coverage-gap plan, so a run always
        surfaces what it does not cover.

        Args:
            scope (str): Coverage scope for the gap plan (see
                `coverage_gap_plan`); default is the changed-lines lens.

        Returns:
            str: The suite output plus the coverage-gap plan.
        """
        return self._run_and_plan(scope, 0, include_output=True)

    # ------------------------------------------------------------------ #
    # Core
    # ------------------------------------------------------------------ #

    def _run_and_plan(
        self, scope: str, threshold: int, include_output: bool
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

        explicit = bool(scope.strip())
        scope_dir, want_diff, ref = _parse_scope(
            scope if explicit else "@diff:origin/main", Path(self.working_directory)
        )
        threshold = threshold if threshold else config.threshold

        ok, output = self._run_command(
            env_.coverage_command, config.coverage_timeout
        )
        report = self._load_report(config)
        if report is None:
            if not ok:
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

        if scope_dir is not None:
            report = _Report(
                [f for f in report.files if _is_within(_norm_abs(f.path, Path(self.working_directory)), scope_dir)],
                report.total_line_rate,
                report.total_function_rate,
            )

        gaps = self._filter_testable(
            self._extract_gaps(report, threshold), False, config.ignore
        )
        untouched = self._find_untouched(report, config, scope_dir)

        patch_pct: float | None = None
        base_ref: str | None = None
        changed: dict[str, set[int]] = {}
        diff_active = False
        if want_diff:
            try:
                base_ref, changed = self._resolve_diff(ref)
            except _GitDiffError as exc:
                if explicit:
                    return f"[coverage error]: {exc}"
                # Default diff ref unavailable (e.g. no origin/main) -> whole repo.
                changed = {}
            else:
                if scope_dir is not None:
                    changed = {
                        p: lines
                        for p, lines in changed.items()
                        if _is_within(p, scope_dir)
                    }
                gaps, assume_uncovered = self._narrow_to_diff(
                    gaps, changed, report, config.ignore
                )
                untouched = []
                patch_pct = self._patch_coverage(
                    report, changed, assume_uncovered
                )
                diff_active = True

        scope_label = "whole project"
        if diff_active:
            scope_label = "changed lines"
        elif scope_dir is not None:
            scope_label = _relative(str(scope_dir), self.working_directory)

        header = [
            "COVERAGE-GAP PLAN (read-only, no model, no lacuna CLI)",
            f"Detected:   {env_.test_runner} ({env_.language})",
            f"Scope:      {scope_label}",
            f"Threshold:  {threshold}%",
            f"Coverage:   lines {report.total_line_rate * 100:.1f}% | "
            f"functions {report.total_function_rate * 100:.1f}%",
            f"Suite:      {'passed' if ok else 'FAILED'}",
        ]
        if not ok and output:
            header.append("Suite tail: " + output[-_FAILURE_TAIL_CHARS:].strip())
        if diff_active and base_ref is not None:
            header.append(
                f"Diff:       vs {base_ref} ({len(changed)} file(s), "
                f"{sum(len(v) for v in changed.values())} line(s))"
            )

        body = self._render_gaps(
            gaps, untouched, patch_pct, Path(self.working_directory)
        )
        text = "\n".join(header) + "\n" + body
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
    ) -> float:
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
        return 100.0 if total == 0 else (covered / total) * 100.0

    def _render_gaps(
        self,
        gaps: list[_Gap],
        untouched: list[_Gap],
        patch_pct: float | None,
        root: Path,
    ) -> str:
        lines: list[str] = []
        if patch_pct is not None:
            lines.append(f"Patch coverage: {patch_pct:.1f}%")
        if not gaps and not untouched:
            lines.append("No coverage gaps found. Nothing uncovered in scope.")
            return "\n".join(lines)

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
