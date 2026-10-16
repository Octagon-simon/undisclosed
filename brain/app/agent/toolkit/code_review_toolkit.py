# Copyright (c) 2026 Simon Ugorji

"""Deterministic code-review tooling -- the in-product equivalent of a
"OpenCodeReview"-style PR reviewer, with **no external LLM token**.

The upstream bot runs deterministic pipelines and then reports line-anchored
findings plus a summary (``found N issue(s)``). This toolkit does the same
review work locally and needs nothing beyond the tools already on the machine:

  - ``run_checks``   -- run the project's typecheck + lint (tsc/pyright/ruff/...)
  - ``review_diff``  -- review a diff: run the checks, scan the changed lines
                        with a built-in ruleset, and return line-anchored
                        findings (``file:line [category/severity] message ->
                        suggestion``) plus a summary header.

Both tools are READ-ONLY: they never modify files and never call a model. The
agent itself reads the findings and applies the fixes -- so the review follows
the typecheck/verification flow without spending a separate review token.

The ruleset mirrors the categories OpenCodeReview uses for a finding
(``bug`` / ``security`` / ``performance`` / ``maintainability`` / ``test`` /
``style``) and draws the concrete checks from its per-language rule docs
(``internal/config/rules/rule_docs/{python,ts_js_tsx_jsx,go}.md`` upstream), the
same docs OCR resolves by path/extension at review time. It is a deterministic
backstop, not a semantic reviewer: it catches secrets, injection sinks,
unsafe deserialization, error-handling and correctness/logic smells, boundary
off-by-ones, debug leftovers, and per-language style-rule violations, but not
arbitrary logic bugs that need whole-program reasoning. The agent's own
reasoning covers the rest -- OCR reaches the same split, delegating to the host
agent in its "delegation mode".

Severity is reported as ``error`` / ``warning`` / ``info`` (OCR's
``critical``/``high``/``medium``/``low`` collapse onto these: critical+high ->
error, medium -> warning, low -> info).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from camel.toolkits import BaseToolkit
from camel.toolkits.function_tool import FunctionTool

from app.agent.toolkit.abstract_toolkit import AbstractToolkit
from app.service.task import Agents

#: Nothing here mutates the workspace, so there is no Ask-mode gate.
WRITE_TOOL_NAMES: set[str] = set()

_MAX_OUTPUT_CHARS = 20_000
_CHECK_TIMEOUT = 300.0
_GIT_TIMEOUT = 120.0

_JS_EXTS = (".js", ".jsx", ".ts", ".tsx")
_TS_EXTS = (".ts", ".tsx")
_GO_EXTS = (".go",)

#: Built-in rules applied to ADDED lines only:
#: (pattern, category, severity, message, suggestion, extensions-or-None).
#: ``extensions=None`` means any language. ``category`` mirrors the
#: OpenCodeReview taxonomy: bug, security, performance, maintainability,
#: test, style, documentation, other.
_RULES: list[tuple[str, str, str, str, str, tuple[str, ...] | None]] = [
    # ------------------------------------------------------------------ #
    # security
    # ------------------------------------------------------------------ #
    (
        r"AKIA[0-9A-Z]{16}",
        "security",
        "error",
        "Possible hardcoded AWS access key.",
        "Move the key to an environment variable / secret store and rotate it.",
        None,
    ),
    (
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        "security",
        "error",
        "Private key committed in source.",
        "Remove it, store the key outside the repo, and rotate it.",
        None,
    ),
    (
        r"ghp_[0-9A-Za-z]{36}|github_pat_[0-9A-Za-z_]{22,}",
        "security",
        "error",
        "Possible hardcoded GitHub token.",
        "Revoke it, store it in a secret, and read it from the environment.",
        None,
    ),
    (
        r"xox[baprs]-[0-9A-Za-z-]{10,}",
        "security",
        "error",
        "Possible hardcoded Slack token.",
        "Revoke it and load the token from a secret store.",
        None,
    ),
    (
        r"sk_live_[0-9A-Za-z]{16,}|AIza[0-9A-Za-z\-_]{35}|sk-[A-Za-z0-9]{20,}",
        "security",
        "error",
        "Possible hardcoded API key / token.",
        "Revoke it and load the value from an env var or secret store.",
        None,
    ),
    (
        r"(?:password|passwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*"
        r"['\"][^'\"]{6,}['\"]",
        "security",
        "error",
        "Hardcoded secret / credential literal.",
        "Read it from config or an env var instead of committing it.",
        None,
    ),
    (
        r"\beval\s*\(|\bexec\s*\(|\bnew\s+Function\s*\(",
        "security",
        "warning",
        "Dynamic code execution (eval/exec/Function) on data can enable "
        "code injection.",
        "Avoid dynamic execution; parse the input or use a safe mapping.",
        (".py", *_JS_EXTS),
    ),
    (
        r"\bos\.system\s*\(",
        "security",
        "warning",
        "os.system() invokes a shell and is injection-prone.",
        "Use subprocess with a list of args and shell=False.",
        (".py",),
    ),
    (
        r"shell\s*=\s*True",
        "security",
        "warning",
        "subprocess with shell=True is injection-prone.",
        "Pass an argument list and leave shell=False.",
        (".py",),
    ),
    (
        r"verify\s*=\s*False",
        "security",
        "warning",
        "TLS verification disabled.",
        "Remove verify=False or scope it to a documented, trusted case.",
        (".py",),
    ),
    (
        r"\b(?:pickle|marshal|cPickle)\.loads?\s*\(|\byaml\.load\s*\(",
        "security",
        "warning",
        "Unsafe deserialization on untrusted data can execute code.",
        "Use a safe format, or yaml.safe_load / json.loads instead.",
        (".py",),
    ),
    (
        r"hashlib\.(?:md5|sha1)\s*\(",
        "security",
        "warning",
        "Weak hash (md5/sha1) used for a cryptographic purpose.",
        "Use sha256+ (or a password KDF) for security-sensitive hashing.",
        (".py",),
    ),
    (
        r"\.(?:execute|executemany|raw|query)\s*\(\s*f['\"]|"
        r"\.(?:execute|executemany)\s*\([^)]*\+\s*",
        "security",
        "warning",
        "SQL built by string interpolation/concatenation.",
        "Use parameterized queries (placeholders + bound params).",
        (".py",),
    ),
    (
        r"dangerouslySetInnerHTML|\.innerHTML\s*=|document\.write\s*\(",
        "security",
        "warning",
        "Raw HTML injection sink (XSS risk).",
        "Sanitize the value or render it as text instead of HTML.",
        _JS_EXTS,
    ),
    (
        r"set(?:Timeout|Interval)\s*\(\s*['\"`]",
        "security",
        "warning",
        "setTimeout/setInterval called with a string (implicit eval).",
        "Pass a function instead of a string.",
        _JS_EXTS,
    ),
    (
        r"\b(?:Array|Object|String|Number|Boolean|Function|Date)\.prototype\b",
        "security",
        "warning",
        "Modifying a native prototype can break unrelated code.",
        "Extend via a wrapper/utility function instead of the prototype.",
        _JS_EXTS,
    ),
    (
        r"chmod\s+777|0o777|\bwrite-all\b",
        "security",
        "warning",
        "Overly broad permissions.",
        "Use the narrowest permissions that work (e.g. 644/755).",
        None,
    ),
    # ------------------------------------------------------------------ #
    # bug (correctness / logic)
    # ------------------------------------------------------------------ #
    (
        r"def\s+\w+\s*\([^)]*=\s*(?:\[\]|\{\})",
        "bug",
        "warning",
        "Mutable default argument (created once, shared across calls).",
        "Default to None and build the list/dict inside the body.",
        (".py",),
    ),
    (
        r"\bis\s+(?:True|False)\b|\bis\s+[\"'\d]",
        "bug",
        "warning",
        "`is` compared against a literal/boolean (identity, not value).",
        "Use == / != for value comparison; keep `is` for None/sentinels.",
        (".py",),
    ),
    (
        r"except\s*:",
        "bug",
        "warning",
        "Bare except swallows everything (incl. KeyboardInterrupt).",
        "Catch `except Exception` at minimum, ideally the specific types.",
        (".py",),
    ),
    (
        r"except\s+[A-Za-z_.]*(?:\s+as\s+\w+)?\s*:\s*pass\b",
        "bug",
        "warning",
        "Exception silently swallowed (except ...: pass).",
        "Handle it, log it, or narrow the except and re-raise.",
        (".py",),
    ),
    (
        r"[^=!<>]==\s*(?:True|False)\b",
        "bug",
        "info",
        "Comparison to True/False via ==.",
        "Use a plain truthiness check instead.",
        (".py",),
    ),
    (
        r"return\s+[\w.]+\s*\([^)]*\)\s*\+\s*1\b",
        "bug",
        "info",
        "Possibly off-by-one arithmetic near a boundary.",
        "Double-check the boundary; prefer a named, tested helper.",
        (".py", ".ts", ".tsx"),
    ),
    (
        r"\bassert\s+",
        "bug",
        "info",
        "assert used where it may run under -O (assertions are stripped).",
        "Validate external input with an explicit check/raise, not assert.",
        (".py",),
    ),
    # ------------------------------------------------------------------ #
    # performance
    # ------------------------------------------------------------------ #
    (
        r"\b(?:logging|logger|log)\.\w+\(\s*f['\"]",
        "performance",
        "info",
        "F-string passed to logging (formatted even when the level is off).",
        "Use lazy logging: log.info('%s', value).",
        (".py",),
    ),
    # ------------------------------------------------------------------ #
    # test
    # ------------------------------------------------------------------ #
    (
        r"\.only\s*\(|\b(?:fit|fdescribe)\s*\(",
        "test",
        "warning",
        "Focused test left in (.only / fit / fdescribe).",
        "Remove the focus so the whole suite runs in CI.",
        _JS_EXTS,
    ),
    (
        r"@pytest\.mark\.skip\b|@unittest\.skip\b",
        "test",
        "info",
        "Skip marker added.",
        "Remove it, or give the skip an explicit, tracked reason.",
        (".py",),
    ),
    # ------------------------------------------------------------------ #
    # maintainability
    # ------------------------------------------------------------------ #
    (
        r"@ts-ignore|@ts-nocheck|eslint-disable",
        "maintainability",
        "info",
        "Suppression directive added.",
        "Prefer fixing the underlying error; if intended, scope it to a line "
        "and add a reason.",
        _JS_EXTS,
    ),
    (
        r"#\s*type:\s*ignore|#\s*noqa",
        "maintainability",
        "info",
        "Type/lint suppression added.",
        "Prefer a real fix; keep any suppression line-scoped with a reason.",
        (".py",),
    ),
    (
        r"\bdebugger\b;",
        "maintainability",
        "warning",
        "Leftover debugger statement.",
        "Remove it before committing.",
        _JS_EXTS,
    ),
    (
        r"console\.(?:log|debug)\s*\(",
        "maintainability",
        "info",
        "Debug logging left in the change.",
        "Remove it or route it through a logger you can disable.",
        _JS_EXTS,
    ),
    (
        r"\bprint\s*\(",
        "maintainability",
        "info",
        "print() left in the change.",
        "Remove it or use the logging module.",
        (".py",),
    ),
    (
        r"\bTODO\b|\bFIXME\b|\bXXX\b",
        "maintainability",
        "info",
        "TODO/FIXME marker added.",
        "Resolve it or link a tracking issue.",
        None,
    ),
    # ------------------------------------------------------------------ #
    # style
    # ------------------------------------------------------------------ #
    (
        r"\bvar\s+[A-Za-z_$]",
        "style",
        "info",
        "`var` declaration (function-scoped, hoisted).",
        "Use let/const instead.",
        _JS_EXTS,
    ),
    (
        r"(?<![=!<>])==(?!=)|(?<![=!])!=(?!=)",
        "style",
        "info",
        "Non-strict equality (== / !=) in JS/TS.",
        "Use === / !== unless you deliberately want type coercion.",
        _JS_EXTS,
    ),
    (
        r":\s*any\b|\bas\s+any\b|<any>",
        "style",
        "info",
        "`any` type used.",
        "Prefer a real type; if truly needed, add a comment explaining why.",
        (".ts", ".tsx"),
    ),
    (
        r"[^=!<>]==\s*None\b|[^=!<>]!=\s*None\b",
        "style",
        "info",
        "Comparison to None via ==/!=.",
        "Use `is None` / `is not None`.",
        (".py",),
    ),
    # ------------------------------------------------------------------ #
    # expanded ruleset -- drawn from OpenCodeReview's per-language rule docs
    # (internal/config/rules/rule_docs/{python,ts_js_tsx_jsx,go}.md). These are
    # single-line, high-precision checks only: OCR resolves the same rule doc by
    # path/extension (rules_system_rules.json), so grouping by extension here
    # mirrors that. Multi-line and semantic logic stays the agent's job.
    # ------------------------------------------------------------------ #
    # --- security (continued) ---
    (
        r"(?<![\w.])compile\s*\(",
        "security",
        "warning",
        "compile() on dynamic input can enable code execution.",
        "Avoid compiling untrusted source; parse or map the input instead.",
        (".py",),
    ),
    (
        r"\bif\s*\([^=!<>]*[^=!<>]=[^=]",
        "bug",
        "warning",
        "Assignment inside an if() condition (likely meant ==).",
        "Use == / === to compare; assign on its own line if it was intended.",
        _JS_EXTS,
    ),
    (
        r"target\s*=\s*[\"']_blank[\"'](?![^>]*rel\s*=\s*[\"'][^\"']*noopener)",
        "security",
        "info",
        "_blank link without rel=noopener (reverse tabnabbing).",
        "Add rel=\"noopener noreferrer\".",
        _JS_EXTS,
    ),
    (
        r"(?:http|https)://(?:localhost|127\.0\.0\.1|"
        r"\d{1,3}(?:\.\d{1,3}){3})(?::\d+)?",
        "security",
        "info",
        "Hardcoded local/self URL in source.",
        "Move the base URL to config/env; do not commit environment-specific "
        "hosts.",
        None,
    ),
    # --- bug (correctness / logic) ---
    (
        r"\bfor\s*\([^;]*;[^;]*<=[^;]*\.length\s*;",
        "bug",
        "info",
        "Loop bound uses `<= ...length` (classic off-by-one).",
        "Use `i < x.length`, or subtract 1 explicitly if inclusive.",
        _JS_EXTS,
    ),
    (
        r"finally\s*\{[^}]*\breturn\b",
        "bug",
        "warning",
        "return inside finally overrides the try/catch result.",
        "Do not return from finally; let the original result propagate.",
        (".js", ".jsx", ".ts", ".tsx"),
    ),
    (
        r"\b(?:panic|log\.Fatal|os\.Exit)\s*\(",
        "bug",
        "warning",
        "panic/Fatal/Exit in a library or request path (not recoverable).",
        "Return an error instead; reserve panics for impossible invariants.",
        _GO_EXTS,
    ),
    (
        r"context\.(?:Background|TODO)\s*\(\s*\)",
        "bug",
        "info",
        "Fresh context where the caller's context should be propagated.",
        "Pass the incoming context so deadlines/cancellation are honored.",
        _GO_EXTS,
    ),
    (
        r"\bexcept\s+Exception\b",
        "bug",
        "info",
        "Broad `except Exception` (wider than the failure being handled).",
        "Catch the specific exception types the guarded call can raise.",
        (".py",),
    ),
    # --- performance ---
    (
        r"http\.(?:Get|Post|Head)\s*\(",
        "performance",
        "info",
        "HTTP helper without a context/timeout (can hang a request path).",
        "Use an http.Client with a context and a timeout.",
        _GO_EXTS,
    ),
    (
        r"\btime\.Sleep\s*\(",
        "performance",
        "info",
        "time.Sleep in a request/worker path blocks the goroutine.",
        "Use a context-aware timer/select when cancellation matters.",
        _GO_EXTS,
    ),
    # --- maintainability / style (Go + React) ---
    (
        r"\b(?:fmt\.Print|fmt\.Println|fmt\.Printf|println)\s*\(",
        "maintainability",
        "info",
        "Debug print left in the change.",
        "Remove it or use a leveled logger.",
        _GO_EXTS,
    ),
    (
        r"\binterface\s*\{\s*\}",
        "style",
        "info",
        "`interface{}` used instead of `any` (Go 1.18+).",
        "Prefer `any` for readability.",
        _GO_EXTS,
    ),
    (
        r"strings\.Replace(?:All)?\s*\([^)]*,\s*-1\s*\)",
        "style",
        "info",
        "strings.Replace with n=-1.",
        "Use strings.ReplaceAll.",
        _GO_EXTS,
    ),
    (
        r"errors\.New\s*\(\s*fmt\.Sprintf\s*\(",
        "style",
        "info",
        "errors.New(fmt.Sprintf(...)) instead of fmt.Errorf.",
        "Use fmt.Errorf(...) directly.",
        _GO_EXTS,
    ),
    (
        r"style\s*=\s*\{\{",
        "style",
        "info",
        "Inline style object in JSX.",
        "Use a class for static styles; keep inline only for dynamic values.",
        _JS_EXTS,
    ),
    (
        r"[^=!<>][=!]=\s*\d+\.\d+",
        "bug",
        "info",
        "Exact float comparison (floating-point results are not exact).",
        "Compare with math.isclose / an explicit tolerance.",
        (".py",),
    ),
]


def _truncate(text: str, limit: int = _MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n… [output truncated]"


def _has_cmd(cmd: str) -> bool:
    """Module-level (CAMEL wraps toolkit methods; keep helpers unbound)."""
    return shutil.which(cmd) is not None


def _scan_added_lines(
    diff_text: str,
) -> list[tuple[str, int, str, str, str, str]]:
    """Return findings as (path, line, category, severity, message, suggestion)."""
    findings: list[tuple[str, int, str, str, str, str]] = []
    current: str | None = None
    new_line = 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            path = raw[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            current = None if path == "/dev/null" else path
        elif raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            new_line = int(match.group(1)) if match else 0
        elif raw.startswith("+") and not raw.startswith("+++"):
            if current is not None:
                content = raw[1:]
                ext = Path(current).suffix.lower()
                for pattern, category, severity, message, suggestion, exts in _RULES:
                    if exts is not None and ext not in exts:
                        continue
                    if re.search(pattern, content):
                        findings.append(
                            (
                                current,
                                new_line,
                                category,
                                severity,
                                message,
                                suggestion,
                            )
                        )
            new_line += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            continue
        else:
            new_line += 1
    return findings


class CodeReviewToolkit(BaseToolkit, AbstractToolkit):
    """Deterministic, read-only code review over the project's diff."""

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
                "working_directory is required for CodeReviewToolkit; review "
                "runs against the task's project directory."
            )
        self.working_directory = str(Path(working_directory).expanduser())

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _git(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", self.working_directory, *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )

    def _is_git_repo(self) -> bool:
        if not _has_cmd("git"):
            return False
        try:
            result = self._git(["rev-parse", "--is-inside-work-tree"])
        except Exception:  # pragma: no cover - defensive
            return False
        return result.returncode == 0 and result.stdout.strip() == "true"

    def _get_diff(self, base: str) -> tuple[str, str]:
        """Return (diff_text, description). Empty diff_text = nothing to review."""
        if not self._is_git_repo():
            return "", "not a git repository"
        if base.strip():
            ref = self._git(["rev-parse", "--verify", "--quiet", base.strip()])
            if ref.returncode == 0:
                for args, desc in (
                    (["diff", "--unified=0", f"{base}...HEAD"], f"{base}...HEAD"),
                    (["diff", "--unified=0", base], base),
                ):
                    result = self._git(args)
                    if result.returncode == 0 and result.stdout.strip():
                        return result.stdout, desc
        for args, desc in (
            (["diff", "--unified=0", "HEAD"], "HEAD vs working tree"),
            (["diff", "--unified=0"], "working tree"),
        ):
            result = self._git(args)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout, desc
        return "", base or "HEAD"

    def _detect_checks(self) -> list[tuple[str, list[str]]]:
        """Detect the project's typecheck + lint commands."""
        wd = Path(self.working_directory)
        checks: list[tuple[str, list[str]]] = []
        has_pkg = (wd / "package.json").is_file()
        if has_pkg and (wd / "tsconfig.json").is_file() and _has_cmd("npx"):
            checks.append(
                ("typecheck (tsc)", ["npx", "--no-install", "tsc", "--noEmit"])
            )
        if has_pkg and _has_cmd("npx"):
            checks.append(("lint (eslint)", ["npx", "--no-install", "eslint", "."]))
        is_py = (
            (wd / "pyproject.toml").is_file()
            or (wd / "setup.cfg").is_file()
            or any(wd.glob("*.py"))
        )
        if is_py:
            if _has_cmd("pyright"):
                checks.append(("typecheck (pyright)", ["pyright"]))
            elif _has_cmd("mypy"):
                checks.append(("typecheck (mypy)", ["mypy", "."]))
            if _has_cmd("ruff"):
                checks.append(("lint (ruff)", ["ruff", "check", "."]))
            elif _has_cmd("flake8"):
                checks.append(("lint (flake8)", ["flake8"]))
        return checks

    def _run_checks(self) -> str:
        checks = self._detect_checks()
        if not checks:
            return (
                "(no typecheck/lint commands detected for this project; "
                "skipping deterministic checks)"
            )
        blocks: list[str] = []
        for name, cmd in checks:
            try:
                result = subprocess.run(
                    cmd,
                    cwd=self.working_directory,
                    capture_output=True,
                    text=True,
                    timeout=_CHECK_TIMEOUT,
                )
            except subprocess.TimeoutExpired:
                blocks.append(f"- {name}: TIMEOUT")
                continue
            except Exception as exc:  # pragma: no cover - defensive
                blocks.append(f"- {name}: error: {exc}")
                continue
            output = ((result.stdout or "") + (result.stderr or "")).strip()
            status = "ok" if result.returncode == 0 else f"FAILED ({result.returncode})"
            block = f"- {name}: {status}"
            if output:
                block += "\n" + _truncate(output)
            blocks.append(block)
        return "\n".join(blocks)

    # ------------------------------------------------------------------ #
    # Tools
    # ------------------------------------------------------------------ #

    def run_checks(self) -> str:
        """Run the project's typecheck + lint commands (read-only).

        Detects the right commands for the project (tsc/pyright for types,
        eslint/ruff/flake8 for lint) and runs them in the working directory.

        Returns:
            str: A status line per check, followed by its output when it fails.
        """
        return self._run_checks()

    def review_diff(self, base: str = "origin/main") -> str:
        """Review the diff and return line-anchored findings (read-only).

        Runs the deterministic checks, then scans the ADDED lines of the diff
        against a built-in ruleset (secrets, injection sinks, swallowed errors,
        correctness/logic smells, debug leftovers, unsafe permissions, ...).
        Writes nothing and calls no model.

        Args:
            base (str): Git ref to diff against (default `origin/main`).
                Falls back to HEAD / the working tree when the ref is absent.

        Returns:
            str: A summary header, the findings as `file:line
            [category/severity] message -> suggestion`, and the deterministic
            check results.
        """
        diff_text, desc = self._get_diff(base)
        if not diff_text.strip():
            return (
                f"🔍 Code review: no changes to review (base: {desc}). "
                "Nothing to report."
            )

        findings = _scan_added_lines(diff_text)
        errors = sum(1 for f in findings if f[3] == "error")
        warnings = sum(1 for f in findings if f[3] == "warning")

        lines = [
            f"🔍 Code review found {len(findings)} issue(s) in this diff "
            f"(base: {desc}).",
            f"   errors: {errors}  warnings: {warnings}  "
            f"info: {len(findings) - errors - warnings}",
        ]
        if findings:
            by_category: dict[str, int] = {}
            for finding in findings:
                by_category[finding[2]] = by_category.get(finding[2], 0) + 1
            lines.append(
                "   by category: "
                + ", ".join(
                    f"{name}: {count}"
                    for name, count in sorted(by_category.items())
                )
            )
        if findings:
            lines.append("")
            for path, line, category, severity, message, suggestion in findings:
                lines.append(
                    f"- {path}:{line} [{category}/{severity}] {message} "
                    f"-> {suggestion}"
                )
        else:
            lines.append("- No rule-based findings on the changed lines.")

        lines.append("")
        lines.append("Deterministic checks:")
        lines.append(self._run_checks())
        lines.append("")
        lines.append(
            "These findings are yours to act on: fix them, or state why a "
            "finding is a false positive / out of scope before finishing."
        )
        return "\n".join(lines)

    def get_tools(self) -> list[FunctionTool]:
        return [
            FunctionTool(self.run_checks),
            FunctionTool(self.review_diff),
        ]
