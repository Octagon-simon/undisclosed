# ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========
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
# ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========

"""Classify a shell command into a governance tier.

Tier 0 reads, tier 1 workspace writes, tier 2 destructive actions, tier 3 hard
blocks. The classifier is intentionally conservative: a command it cannot
recognise is a tier 1 write, and a blocked binary is rejected even when it
appears inside `bash -c`, command substitution, or a pipe.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from app.model.enums import ApprovalScope as CommandScope


class CommandTier(IntEnum):
    """Governance tier for a shell command."""

    READ_ONLY = 0
    WORKSPACE_WRITE = 1
    DESTRUCTIVE = 2
    BLOCKED = 3


@dataclass(frozen=True)
class CommandAssessment:
    """Result of classifying one command line."""

    tier: CommandTier
    reason: str
    segments: tuple[str, ...] = ()
    scopes: tuple[CommandScope, ...] = ()

    @property
    def blocked(self) -> bool:
        return self.tier == CommandTier.BLOCKED


# Always rejected, in every mode. Approval cannot override these.
_BLOCKED_BINARIES = frozenset(
    {
        "rm",
        "rmdir",
        "rd",
        "del",
        "erase",
        "remove-item",
        "unlink",
        "shred",
        "sudo",
        "su",
        "doas",
        "shutdown",
        "reboot",
        "halt",
        "poweroff",
        "telinit",
        "fdisk",
        "sfdisk",
        "gdisk",
        "parted",
        "dd",
        "chroot",
        "format",
        "diskpart",
        "clear-disk",
    }
)

_DESTRUCTIVE_BINARIES = frozenset(
    {
        "kill",
        "pkill",
        "killall",
        "taskkill",
        "mount",
        "umount",
        "systemctl",
        "launchctl",
        "crontab",
        "ssh",
    }
)

_READ_ONLY_BINARIES = frozenset(
    {
        "[",
        "[[",
        "ag",
        "arch",
        "basename",
        "base64",
        "cat",
        "cksum",
        "cmp",
        "comm",
        "column",
        "cut",
        "date",
        "df",
        "diff",
        "dirname",
        "du",
        "echo",
        "expand",
        "false",
        "fd",
        "file",
        "fold",
        "free",
        "grep",
        "groups",
        "head",
        "hexdump",
        "hostname",
        "htop",
        "id",
        "join",
        "jq",
        "locale",
        "ls",
        "md5sum",
        "nl",
        "nproc",
        "od",
        "paste",
        "pbcopy",
        "pbpaste",
        "printenv",
        "printf",
        "ps",
        "pwd",
        "readlink",
        "realpath",
        "rev",
        "rg",
        "sha1sum",
        "sha256sum",
        "shasum",
        "sleep",
        "sort",
        "stat",
        "strings",
        "tac",
        "tail",
        "test",
        "top",
        "tr",
        "tree",
        "true",
        "type",
        "uname",
        "uniq",
        "uptime",
        "wc",
        "whereis",
        "which",
        "whoami",
        "zcat",
    }
)

_WRITE_BINARIES = frozenset(
    {
        "chmod",
        "chown",
        "cp",
        "install",
        "ln",
        "mkdir",
        "mv",
        "rsync",
        "tee",
        "touch",
        "truncate",
        "zip",
        "unzip",
    }
)

_TEST_BINARIES = frozenset(
    {
        "pytest",
        "py.test",
        "jest",
        "vitest",
        "mocha",
        "eslint",
        "ruff",
        "flake8",
        "mypy",
        "pyright",
        "black",
        "prettier",
        "stylelint",
    }
)

_TEST_SCRIPTS = frozenset(
    {
        "test",
        "tests",
        "test:unit",
        "test:integration",
        "test:e2e",
        "lint",
        "typecheck",
        "type-check",
        "check",
        "format:check",
    }
)

_DEPLOY_BINARIES = frozenset(
    {
        "vercel",
        "netlify",
        "firebase",
        "serverless",
        "sls",
        "fly",
        "flyctl",
        "heroku",
        "kubectl",
        "terraform",
        "pulumi",
        "aws",
        "gcloud",
        "az",
    }
)

_DEPLOY_READ_SUBCOMMANDS = frozenset(
    {
        "get",
        "list",
        "describe",
        "status",
        "logs",
        "show",
        "output",
        "plan",
        "validate",
        "diff",
        "version",
        "info",
        "whoami",
    }
)

_SHELL_BINARIES = frozenset({"sh", "bash", "zsh", "dash"})

_FIND_EXEC_FLAGS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
_FIND_EXEC_TOKENS = frozenset({"{}", ";", "+", "\\;"})

# Builtins that only mutate the shell process itself, never the workspace.
# Without this, `cd <dir> && ls` fell through to "not a known read-only
# command" and the approval card claimed a read-only listing wrote files.
_SHELL_STATE_BUILTINS = frozenset(
    {
        ":",
        "alias",
        "cd",
        "declare",
        "dirs",
        "export",
        "false",
        "jobs",
        "local",
        "popd",
        "pushd",
        "set",
        "shift",
        "true",
        "typeset",
        "umask",
        "unalias",
        "unset",
        "wait",
    }
)

_PYTHON_TEST_MODULES = frozenset(
    {"pytest", "unittest", "ruff", "mypy", "pyright", "flake8", "json.tool"}
)

_DESTRUCTIVE_SQL = re.compile(
    r"\b("
    r"drop\s+(table|database|schema|index|collection)"
    r"|truncate\s+table"
    r"|delete\s+from\s+[\w.\"'`]+\s*(;|$)"
    r"|dropdatabase\s*\("
    r"|flushall|flushdb"
    r")",
    re.IGNORECASE,
)

_SUBSTITUTION = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")

# Delete calls a script can make without invoking a blocked binary. The
# literal targets are checked against the workspace: deletion is allowed
# inside it (the task may legitimately replace a component) and is a hard
# block anywhere else.
_DELETE_CALL = re.compile(
    r"(?:os\.(?:remove|unlink|rmdir)"
    r"|shutil\.rmtree"
    r"|Path\([^)]*\)\.(?:unlink|rmdir)"
    r"|fs\.(?:unlink|unlinkSync|rm|rmSync|rmdir|rmdirSync)"
    r"|\.(?:unlink|rmdir))\s*\("
)
_PATH_LITERAL = re.compile(r"""Path\(\s*['"]([^'"]+)['"]\s*\)""")
_DELETE_ARG_LITERAL = re.compile(r"""\s*(?:path\s*=\s*)?['"]([^'"]+)['"]""")

# Inline code can hand the command to another process, where the static
# patterns above never see it. `os.system("rm -rf /tmp/x")` was classified as
# a plain workspace write and ran in Auto with no approval.
_INLINE_PROCESS_SPAWN = re.compile(
    r"(?:"
    r"os\.(?:system|popen|fork|exec\w*|spawn\w*)"
    r"|subprocess\.\w+"
    r"|pty\.spawn"
    r"|child_process"
    r"|__import__\s*\("
    r"|importlib\.import_module"
    r")"
)

_INLINE_PYTHON_FLAGS = frozenset({"-c", "-"})
_INLINE_NODE_FLAGS = frozenset({"-e", "-p", "--eval", "--print"})

_WRITE_REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>"})

_DEV_NULL_TARGETS = frozenset({"/dev/null", "nul", "$null"})

# Write binaries whose path arguments can leave the workspace. These stay
# workspace writes when the target is inside the project; a target outside it
# becomes destructive so it prompts in every mode.
_WRITE_ALL_TARGETS = frozenset(
    {"chmod", "chown", "mkdir", "tee", "touch", "truncate"}
)
_WRITE_LAST_TARGET = frozenset({"cp", "install", "ln", "mv", "rsync"})
_WRITE_FIRST_TARGET = frozenset({"zip"})


def _write_targets(name: str, args: list[str]) -> list[str]:
    """Literal write targets a command names, best-effort."""
    if name in _WRITE_ALL_TARGETS:
        return [arg for arg in args if not arg.startswith("-")]
    if name in {"cp", "install", "ln", "mv"}:
        for flag in ("-t", "--target-directory"):
            if flag in args:
                index = args.index(flag)
                if index + 1 < len(args):
                    return [args[index + 1]]
    values = [arg for arg in args if not arg.startswith("-")]
    if name in _WRITE_LAST_TARGET:
        return values[-1:]
    if name in _WRITE_FIRST_TARGET:
        return values[:1]
    return []


def _write_outside_workspace(segment: str, workspace: Path) -> str:
    """First literal write target in `segment` that resolves outside."""
    tokens = _tokenize(segment)
    for index, token in enumerate(tokens):
        if token not in _WRITE_REDIRECTS or index + 1 >= len(tokens):
            continue
        target = tokens[index + 1].strip("'\"")
        if target in _DEV_NULL_TARGETS:
            continue
        if _escapes_workspace(target, workspace):
            return target

    stripped = _strip_prefixes(tokens)
    if not stripped:
        return ""
    name = _binary(stripped[0])
    for target in _write_targets(name, stripped[1:]):
        if target in _DEV_NULL_TARGETS:
            continue
        if _escapes_workspace(target, workspace):
            return target
    return ""


def _delete_targets(command: str) -> list[str]:
    """Literal paths a script would delete, best-effort."""
    targets = list(_PATH_LITERAL.findall(command))
    for match in _DELETE_CALL.finditer(command):
        literal = _DELETE_ARG_LITERAL.match(command, match.end())
        if literal is not None:
            targets.append(literal.group(1))
    seen: list[str] = []
    for target in targets:
        if target not in seen:
            seen.append(target)
    return seen


def _escapes_workspace(target: str, workspace: Path) -> bool:
    """True when a literal target resolves outside the workspace.

    Relative targets resolve against the workspace because that is the shell's
    cwd. ``~`` and environment variables are expanded first, so
    ``os.remove("~/x")`` cannot slip through as ``<workspace>/~/x``.
    """
    expanded = os.path.expandvars(os.path.expanduser(target.strip()))
    if not expanded:
        return False
    path = Path(expanded)
    if not path.is_absolute():
        path = workspace / path
    try:
        path.resolve().relative_to(workspace)
    except (OSError, ValueError):
        return True
    return False


def assess_command(
    command: str | None, workspace: str | Path | None = None
) -> CommandAssessment:
    """Classify a command line, taking the highest tier of its segments.

    When ``workspace`` is given, a script that deletes a literal path outside
    it is tier 3: deletion is allowed inside the project only.
    """
    text = (command or "").strip()
    if not text:
        return CommandAssessment(CommandTier.READ_ONLY, "empty command")

    segments = _split_segments(text)
    if not segments:
        return CommandAssessment(CommandTier.READ_ONLY, "empty command")

    best = CommandTier.READ_ONLY
    reason = "read-only"
    scopes: list[CommandScope] = []
    for index, segment in enumerate(segments):
        tier, segment_reason = _classify_segment(segment)
        if index == 0 or tier > best:
            best = tier
            reason = segment_reason
        for scope in _classify_scopes(segment):
            if scope not in scopes:
                scopes.append(scope)

    if workspace and best != CommandTier.BLOCKED:
        root = Path(workspace).expanduser().resolve()
        for segment in segments:
            escape = _write_outside_workspace(segment, root)
            if escape:
                best = max(best, CommandTier.DESTRUCTIVE)
                reason = (
                    f"writes {escape} outside the workspace; that needs "
                    "approval in every mode"
                )
                break

    if workspace and best != CommandTier.BLOCKED and _DELETE_CALL.search(text):
        root = Path(workspace).expanduser().resolve()
        targets = _delete_targets(text)
        escapes = [
            target for target in targets if _escapes_workspace(target, root)
        ]
        if escapes:
            best = CommandTier.BLOCKED
            reason = (
                f"deletes {escapes[0]} outside the workspace; deletion is "
                "only allowed inside the project"
            )
        elif not targets:
            # A variable or a glob: the target cannot be checked statically,
            # so the call needs an approval in every mode.
            best = max(best, CommandTier.DESTRUCTIVE)
            reason = "deletes files it cannot scope"

    return CommandAssessment(best, reason, tuple(segments), tuple(scopes))


def classify_scopes(command: str | None) -> tuple[CommandScope, ...]:
    """Return every suppression scope present in a command line."""
    text = (command or "").strip()
    if not text:
        return ()

    scopes: list[CommandScope] = []
    for segment in _split_segments(text):
        for scope in _classify_scopes(segment):
            if scope not in scopes:
                scopes.append(scope)
    return tuple(scopes)


def is_blocked(
    command: str | None, workspace: str | Path | None = None
) -> bool:
    """True when the command contains a tier 3 action."""
    return assess_command(command, workspace).blocked


def describe_tier(tier: CommandTier) -> str:
    """Short label used in tool results and the approval card.

    Tier 1 is "may change files", not "writes files": it covers commands whose
    side effects are not knowable from the command line (running a script,
    `python -c`), and a definite-write label there was misleading.
    """
    return {
        CommandTier.READ_ONLY: "Read only",
        CommandTier.WORKSPACE_WRITE: "May change files",
        CommandTier.DESTRUCTIVE: "Destructive",
        CommandTier.BLOCKED: "Blocked",
    }[tier]


def describe_scope(scope: CommandScope) -> str:
    """Human label for a suppression scope."""
    return {
        CommandScope.FILE_READS: "File reads",
        CommandScope.FILE_WRITES: "File writes",
        CommandScope.BUILDS_TESTS: "Builds & tests",
        CommandScope.DEPENDENCY_INSTALLS: "Dependency installs",
        CommandScope.GIT_ADD_COMMIT: "Git add & commit",
        CommandScope.CODE_EXECUTION: "Runs code",
    }[scope]


#: Flags that only print version/help text and exit. Applied to any binary
#: before the unknown-command fallback, so `node -v` is not a workspace write.
_INFO_FLAGS = frozenset(
    {
        "-v",
        "-V",
        "-version",
        "--version",
        "-h",
        "--help",
        "help",
        "--help-all",
    }
)


def _is_info_invocation(args: list[str]) -> bool:
    if not args:
        return False
    # `node -v`, `npm --version`; not `tool -v --other` with extra work flags.
    return args[0] in _INFO_FLAGS and len(args) <= 2


def summarize_command(command: str | None, limit: int = 4) -> str:
    """One short clause describing what the command will do.

    Deterministic, derived from the command line, not a second model call.
    Used as the approval card's plain-language line so the user sees intent
    before the raw command.
    """
    text = (command or "").strip()
    if not text:
        return ""

    phrases: list[str] = []
    for segment in _split_segments(text):
        phrase = _summarize_segment(segment)
        if not phrase or (phrases and phrases[-1] == phrase):
            continue
        phrases.append(phrase)
        if len(phrases) >= limit:
            break

    if not phrases:
        return ""
    if len(phrases) == 1:
        return phrases[0]
    return ", ".join(phrases[:-1]) + ", then " + phrases[-1]


def _summarize_segment(segment: str) -> str:
    tokens = _tokenize(segment)
    stripped = _strip_prefixes(tokens)
    if not stripped:
        return ""

    name = _binary(stripped[0])
    args = stripped[1:]
    positional = [arg for arg in args if not arg.startswith("-")]

    if name in _SHELL_STATE_BUILTINS:
        return ""
    if _is_info_invocation(args):
        return f"check the {name} version"
    if name in {"ls", "dir"}:
        return "list files"
    if name in {"find", "fd"}:
        return "search for files"
    if name == "tree":
        return "show the folder tree"
    if name in {"cat", "head", "tail", "less", "more"}:
        return "read a file"
    if name in {"grep", "egrep", "fgrep", "rg", "ag"}:
        return "search file contents"
    if name in {"echo", "printf"}:
        return "print a message"
    if name == "pwd":
        return "print the working directory"
    if name in {"which", "whereis", "type"}:
        return "locate an executable"
    if name in {"whoami", "id", "groups"}:
        return "check the current user"
    if name in {"uname", "hostname", "df", "du", "ps", "top", "htop", "uptime"}:
        return "inspect the system"
    if name == "git":
        return _summarize_git(positional)
    if name in {"npm", "pnpm", "yarn", "bun"}:
        return _summarize_node_tool(name, positional)
    if name in {"python", "python3", "py"}:
        return _summarize_python(args)
    if name in {"node", "nodejs"}:
        return _summarize_node(args)
    if name in {"pytest", "jest", "vitest", "mocha", "playwright", "cypress"}:
        return "run the tests"
    if name in _BUILD_BINARIES:
        return f"run {name}"
    if name in _DEPENDENCY_BINARIES:
        return "install dependencies"
    if name in _READ_BINARIES:
        return "read files"
    if name in _WRITE_BINARIES:
        return "write files"
    if name == "make" and positional and positional[0] in _TEST_SCRIPTS:
        return "run the tests"
    return f"run {name}"


def _summarize_git(positional: list[str]) -> str:
    if not positional:
        return "inspect git"
    sub = positional[0]
    if sub in {"status", "branch", "remote", "config"}:
        return "check the git state"
    if sub in {"diff", "log", "show", "blame"}:
        return "inspect git history"
    if sub == "add":
        return "stage changes"
    if sub == "commit":
        return "commit changes"
    return f"run git {sub}"


def _summarize_node_tool(name: str, positional: list[str]) -> str:
    if not positional:
        return f"run {name}"
    sub = positional[0]
    if sub in {"test", "t"}:
        return "run the tests"
    if sub in _PACKAGE_WRITE_SUBCOMMANDS:
        return "install dependencies"
    if sub in {"run", "run-script"}:
        script = positional[1] if len(positional) > 1 else ""
        if script in _TEST_SCRIPTS or script.startswith(
            ("test", "lint", "typecheck", "type-check", "check")
        ):
            return "run the checks"
        return f"run the {script} script" if script else f"run {name}"
    if sub in {"ls", "list", "view", "info", "outdated", "why", "audit"}:
        return f"inspect the {name} project"
    return f"run {name} {sub}"


def _summarize_python(args: list[str]) -> str:
    if args and args[0] == "-m":
        module = args[1] if len(args) > 1 else ""
        if module in _PYTHON_TEST_MODULES:
            return "run the tests"
        return f"run the {module} module" if module else "run a Python module"
    if args and args[0] in {"-c", "-"}:
        return "run a short Python snippet"
    if args:
        return "run a Python script"
    return "start Python"


def _summarize_node(args: list[str]) -> str:
    if args and args[0] in {"-e", "-p", "--eval", "--print"}:
        return "run a short JavaScript snippet"
    if args:
        return "run a JavaScript script"
    return "start Node"


_READ_BINARIES = frozenset(
    {
        "ls",
        "cat",
        "head",
        "tail",
        "less",
        "more",
        "rg",
        "grep",
        "egrep",
        "fgrep",
        "find",
        "fd",
        "tree",
        "stat",
        "wc",
        "file",
        "pwd",
        "printenv",
        "which",
        "whereis",
        "du",
        "df",
        "ps",
        "uname",
        "whoami",
        "date",
        "echo",
        "printf",
        "basename",
        "dirname",
        "realpath",
        "readlink",
        "shasum",
        "md5sum",
        "sha256sum",
        "diff",
        "cmp",
        "jq",
        "yq",
    }
)

_WRITE_BINARIES = frozenset(
    {
        "mkdir",
        "touch",
        "cp",
        "mv",
        "ln",
        "tee",
        "chmod",
        "chown",
        "truncate",
    }
)

_BUILD_BINARIES = frozenset(
    {
        "tsc",
        "eslint",
        "prettier",
        "pytest",
        "jest",
        "vitest",
        "mocha",
        "ava",
        "playwright",
        "cypress",
        "ruff",
        "mypy",
        "pyright",
        "flake8",
        "black",
        "make",
        "cmake",
        "gradle",
        "mvn",
        "rake",
        "dotnet",
    }
)

_DEPENDENCY_BINARIES = frozenset(
    {
        "pip",
        "pip3",
        "poetry",
        "conda",
        "brew",
        "apt",
        "apt-get",
        "yum",
        "dnf",
        "pacman",
        "gem",
        "composer",
    }
)

_GIT_READ_SUBCOMMANDS = frozenset(
    {
        "status",
        "diff",
        "log",
        "show",
        "rev-parse",
        "describe",
        "blame",
        "grep",
        "ls-files",
        "config",
        "remote",
    }
)

_GIT_WRITE_SUBCOMMANDS = frozenset(
    {
        "add",
        "commit",
        "checkout",
        "switch",
        "merge",
        "stash",
        "tag",
        "cherry-pick",
        "revert",
        "restore",
        "mv",
    }
)

_PACKAGE_WRITE_SUBCOMMANDS = frozenset(
    {"install", "i", "add", "ci", "update", "up", "upgrade", "sync", "lock"}
)


def _classify_scopes(segment: str) -> tuple[CommandScope, ...]:
    """Map one command segment to the scopes it would suppress."""
    tokens = _tokenize(segment)
    stripped = _strip_prefixes(tokens)
    if not stripped:
        return ()

    name = _binary(stripped[0])
    args = stripped[1:]
    positional = [arg.lower() for arg in args if not arg.startswith("-")]

    if name in _SHELL_BINARIES:
        inner = _shell_inner(args)
        return classify_scopes(inner) if inner else ()

    tier, _ = _classify_segment(segment)
    if tier == CommandTier.BLOCKED:
        return ()

    if name in _SHELL_STATE_BUILTINS:
        return ()
    if name == "git":
        return _git_scopes(positional)
    if name in {"npm", "pnpm", "yarn", "bun"}:
        if _is_info_invocation(args):
            return (CommandScope.FILE_READS,)
        return _node_scopes(positional)
    if name == "npx":
        if positional and _binary(positional[0]) in _BUILD_BINARIES:
            return (CommandScope.BUILDS_TESTS,)
        return ()
    if name in _DEPENDENCY_BINARIES:
        return (CommandScope.DEPENDENCY_INSTALLS,)
    if name == "uv":
        if positional and positional[0] in {"add", "sync", "lock", "pip"}:
            return (CommandScope.DEPENDENCY_INSTALLS,)
        if positional and positional[0] == "run":
            inner = positional[1:]
            if inner and _binary(inner[0]) in _BUILD_BINARIES:
                return (CommandScope.BUILDS_TESTS,)
            return ()
        return ()
    if name in {"go", "cargo"}:
        if positional and positional[0] in {"get", "add", "install"}:
            return (CommandScope.DEPENDENCY_INSTALLS,)
        return (CommandScope.BUILDS_TESTS,)
    if name in _BUILD_BINARIES:
        return (CommandScope.BUILDS_TESTS,)
    if name in {"python", "python3", "py"}:
        return _python_scopes(args)
    if name in {"node", "nodejs"}:
        return _node_runtime_scopes(args)
    if name == "find":
        # A `-exec` payload can write; scoping it as reads would let the
        # write ride in on an allowlist that only granted File reads.
        for index, arg in enumerate(args):
            if arg in _FIND_EXEC_FLAGS:
                inner = _find_exec_tokens(args[index + 1 :])
                inner_scopes = classify_scopes(" ".join(inner)) if inner else ()
                if inner_scopes:
                    return inner_scopes
        return (CommandScope.FILE_READS,)
    if name in _READ_BINARIES:
        return (CommandScope.FILE_READS,)
    if name in _WRITE_BINARIES:
        return (CommandScope.FILE_WRITES,)
    if tier == CommandTier.READ_ONLY:
        return (CommandScope.FILE_READS,)
    if tier == CommandTier.WORKSPACE_WRITE:
        return (CommandScope.FILE_WRITES,)
    return ()


def _shell_command_index(args: list[str]) -> int | None:
    """Index of the flag that carries a shell command string.

    Short flags bundle, so `bash -lc 'rm -rf /'` is the same as
    `bash -c ...` and must be classified instead of being read as a script
    name. `--norc` is not a command flag, so long options are excluded.
    """
    for index, arg in enumerate(args):
        if arg == "--command":
            return index
        if arg.startswith("-") and not arg.startswith("--") and "c" in arg[1:]:
            return index
    return None


def _shell_inner(args: list[str]) -> str:
    index = _shell_command_index(args)
    if index is not None and index + 1 < len(args):
        return " ".join(args[index + 1 :])
    return ""


def _git_scopes(positional: list[str]) -> tuple[CommandScope, ...]:
    if not positional:
        return (CommandScope.FILE_READS,)
    sub = positional[0]
    if sub in _GIT_READ_SUBCOMMANDS:
        return (CommandScope.FILE_READS,)
    if sub == "branch":
        listing = len(positional) == 1 or positional[1].startswith(
            ("-a", "-r", "--list", "-v")
        )
        return (
            (CommandScope.FILE_READS,)
            if listing
            else (CommandScope.GIT_ADD_COMMIT,)
        )
    if sub in _GIT_WRITE_SUBCOMMANDS:
        return (CommandScope.GIT_ADD_COMMIT,)
    return ()


def _node_scopes(positional: list[str]) -> tuple[CommandScope, ...]:
    if not positional:
        return (CommandScope.BUILDS_TESTS,)
    sub = positional[0]
    if sub in _PACKAGE_WRITE_SUBCOMMANDS:
        return (CommandScope.DEPENDENCY_INSTALLS,)
    return (CommandScope.BUILDS_TESTS,)


def _node_runtime_scopes(args: list[str]) -> tuple[CommandScope, ...]:
    if _is_info_invocation(args):
        return (CommandScope.FILE_READS,)
    if args and args[0] in {"--check"}:
        return (CommandScope.FILE_READS,)
    return (CommandScope.CODE_EXECUTION,)


def _python_scopes(args: list[str]) -> tuple[CommandScope, ...]:
    if _is_info_invocation(args):
        return (CommandScope.FILE_READS,)
    for index, arg in enumerate(args):
        if arg == "-m" and index + 1 < len(args):
            module = args[index + 1].lower()
            if module in _PYTHON_TEST_MODULES:
                return (CommandScope.BUILDS_TESTS,)
            return (CommandScope.CODE_EXECUTION,)
    return (CommandScope.CODE_EXECUTION,)


def _split_segments(command: str) -> list[str]:
    """Split on shell control operators, respecting quotes and heredocs.

    Newlines separate commands too, so a multi-line script cannot hide a
    blocked command after a harmless first line. A heredoc body is DATA for a
    command like ``cat > script <<EOF``: it must stay attached to that command
    instead of being parsed as a burst of separate shell commands.
    """
    segments: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    # (delimiter, strip_leading_tabs) for heredocs whose body starts on the
    # next newline. Multiple heredocs may be queued on one command line.
    pending_heredocs: list[tuple[str, bool]] = []
    i = 0
    while i < len(command):
        char = command[i]

        if quote is not None:
            buf.append(char)
            if char == "\\" and quote == '"' and i + 1 < len(command):
                buf.append(command[i + 1])
                i += 2
                continue
            if char == quote:
                quote = None
            i += 1
            continue

        if char in ("'", '"'):
            quote = char
            buf.append(char)
            i += 1
            continue

        if command.startswith("<<", i) and not command.startswith("<<<", i):
            # `<<EOF` / `<<-'EOF'`: parse the delimiter now, then consume the
            # body on the next newline.
            start = i
            j = i + 2
            strip_tabs = False
            if j < len(command) and command[j] == "-":
                strip_tabs = True
                j += 1
            while j < len(command) and command[j] in " \t":
                j += 1
            delimiter = ""
            if j < len(command) and command[j] in ("'", '"'):
                delimiter_quote = command[j]
                j += 1
                delimiter_chars: list[str] = []
                while j < len(command):
                    current = command[j]
                    if (
                        current == "\\"
                        and delimiter_quote == '"'
                        and j + 1 < len(command)
                    ):
                        delimiter_chars.append(command[j + 1])
                        j += 2
                        continue
                    if current == delimiter_quote:
                        j += 1
                        break
                    delimiter_chars.append(current)
                    j += 1
                delimiter = "".join(delimiter_chars)
            else:
                delimiter_start = j
                while j < len(command) and command[j] not in " \t\n;|&()`":
                    j += 1
                delimiter = command[delimiter_start:j]
            # A shell interpreter executes its heredoc body as commands, so
            # keep the old behaviour for it: let the newline split the body
            # and classify every line (a blocked `rm` inside must still
            # latch). For `cat` / `tee` / a script runner the body is data.
            head_tokens = _strip_prefixes(_tokenize("".join(buf)))
            head_name = _binary(head_tokens[0]) if head_tokens else ""
            executes_stdin = head_name in _SHELL_BINARIES or head_name in {
                "eval",
                "source",
                ".",
            }
            buf.append(command[start:j])
            if delimiter and not executes_stdin:
                pending_heredocs.append((delimiter, strip_tabs))
            i = j
            continue

        if char == "\n" and pending_heredocs:
            buf.append("\n")
            i += 1
            for delimiter, strip_tabs in pending_heredocs:
                while i < len(command):
                    line_end = command.find("\n", i)
                    if line_end == -1:
                        line_end = len(command)
                    line = command[i:line_end]
                    candidate = line.lstrip("\t") if strip_tabs else line
                    buf.append(line)
                    if line_end < len(command):
                        buf.append("\n")
                        i = line_end + 1
                    else:
                        i = len(command)
                    if candidate == delimiter:
                        break
            pending_heredocs.clear()
            # The newline after the closing delimiter ends the command that
            # owned the heredoc; the next line is a new command.
            segments.append("".join(buf))
            buf = []
            continue

        if char == "\\" and i + 1 < len(command):
            buf.append(char)
            buf.append(command[i + 1])
            i += 2
            continue

        if command.startswith("$(", i):
            segments.append("".join(buf))
            buf = []
            i += 2
            continue

        if command.startswith("&&", i) or command.startswith("||", i):
            segments.append("".join(buf))
            buf = []
            i += 2
            continue

        if char == "&" and (
            (i > 0 and command[i - 1] in "<>")
            or (i + 1 < len(command) and command[i + 1] == ">")
        ):
            # part of a redirection (2>&1, &>file), not a background job
            buf.append(char)
            i += 1
            continue

        if char in ";|&\n()`":
            segments.append("".join(buf))
            buf = []
            i += 1
            continue

        buf.append(char)
        i += 1

    segments.append("".join(buf))
    return [segment.strip() for segment in segments if segment.strip()]


def _tokenize(segment: str) -> list[str]:
    lexer = shlex.shlex(segment, posix=True, punctuation_chars="();<>|&$`")
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        # Unbalanced quotes: fall back to a whitespace split so a blocked
        # binary is still caught in the common `rm -rf "dir` case.
        return segment.split()


def _binary(token: str) -> str:
    name = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
    for suffix in (".exe", ".cmd", ".bat", ".ps1", ".com"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name


def _strip_prefixes(tokens: list[str]) -> list[str]:
    """Drop env assignments and wrappers before the real command word."""
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", token):
            index += 1
            continue
        name = _binary(token)
        if name in {
            "env",
            "command",
            "nohup",
            "time",
            "exec",
            "builtin",
            "then",
            "do",
            "else",
            "elif",
            "!",
        }:
            index += 1
            while index < len(tokens) and tokens[index].startswith("-"):
                index += 1
            continue
        break
    return tokens[index:]


def _classify_segment(segment: str) -> tuple[CommandTier, str]:
    tokens = _tokenize(segment)
    stripped = _strip_prefixes(tokens)
    if not stripped:
        return CommandTier.READ_ONLY, "no command"

    name = _binary(stripped[0])
    args = stripped[1:]

    tier, reason = _classify_command(name, args, segment)

    if _writes_stdout_to_file(tokens) and tier < CommandTier.WORKSPACE_WRITE:
        tier = CommandTier.WORKSPACE_WRITE
        reason = "redirects output to a file"

    subst_tier, subst_reason = _classify_substitutions(segment)
    if subst_tier > tier:
        tier = subst_tier
        reason = f"command substitution: {subst_reason}"

    return tier, reason


def _classify_substitutions(segment: str) -> tuple[CommandTier, str]:
    best = CommandTier.READ_ONLY
    reason = ""
    for match in _SUBSTITUTION.finditer(segment):
        inner = match.group(1) or match.group(2) or ""
        assessment = assess_command(inner)
        if assessment.tier > best:
            best = assessment.tier
            reason = assessment.reason
    return best, reason


def _writes_stdout_to_file(tokens: list[str]) -> bool:
    for index, token in enumerate(tokens):
        if token not in _WRITE_REDIRECTS:
            continue
        target_index = index + 1
        while target_index < len(tokens) and (
            tokens[target_index] in {"1", "2", "&", "&1", "&2"}
            or re.match(r"^&\d+$", tokens[target_index])
        ):
            target_index += 1
        if target_index >= len(tokens):
            # File-descriptor duplication (`2>&1`), not a file write.
            continue
        target = tokens[target_index]
        if target.replace("\\", "/").lower() not in _DEV_NULL_TARGETS:
            return True
    return False


def _classify_command(
    name: str, args: list[str], segment: str
) -> tuple[CommandTier, str]:
    if name.startswith("mkfs."):
        return CommandTier.BLOCKED, f"`{name}` formats a filesystem"
    if name in _BLOCKED_BINARIES:
        return CommandTier.BLOCKED, f"`{name}` is blocked in every mode"
    if name == "diskutil":
        if args and args[0] in {"list", "info", "activity"}:
            return CommandTier.READ_ONLY, "diskutil inspection"
        return CommandTier.BLOCKED, "`diskutil` modifies a disk"
    if name in _DESTRUCTIVE_BINARIES:
        return CommandTier.DESTRUCTIVE, f"`{name}` can affect the host"
    if name in _SHELL_STATE_BUILTINS:
        return CommandTier.READ_ONLY, f"`{name}` only changes shell state"
    if name == "git":
        return _classify_git(args)

    if name in {"npm", "pnpm", "yarn", "bun"}:
        return _classify_node_tool(name, args)
    if name == "npx":
        return _classify_wrapped_command(args)
    if name in {"python", "python3", "py"}:
        return _classify_python(args, segment)
    if name in {"node", "nodejs"}:
        return _classify_node(args, segment)
    if name in {"pip", "pip3", "uv", "poetry"}:
        return _classify_packages(name, args)
    if name in {"go", "cargo", "rustc"}:
        return _classify_build(name, args)
    if name == "make":
        target = args[0] if args else ""
        if target in _TEST_SCRIPTS:
            return CommandTier.READ_ONLY, f"`make {target}`"
        return CommandTier.WORKSPACE_WRITE, "make can write build output"
    if name in {"docker", "podman"}:
        return _classify_docker(args)
    if name in _DEPLOY_BINARIES:
        sub = args[0] if args else ""
        if sub in _DEPLOY_READ_SUBCOMMANDS:
            return CommandTier.READ_ONLY, f"`{name} {sub}`"
        return CommandTier.DESTRUCTIVE, f"`{name}` can change remote state"
    if name in {"psql", "mysql", "sqlite3", "mongosh", "mongo", "redis-cli"}:
        if _DESTRUCTIVE_SQL.search(" ".join(args)) or any(
            arg in {"flushall", "flushdb"} for arg in args
        ):
            return CommandTier.DESTRUCTIVE, "SQL/DB command destroys data"
        return CommandTier.WORKSPACE_WRITE, f"`{name}` can write to a database"

    if name in _SHELL_BINARIES:
        return _classify_shell(name, args)
    if name in {"powershell", "pwsh"}:
        return _classify_powershell(args)
    if name == "cmd":
        return _classify_cmd(args)
    if name in {"eval", "source", "."}:
        if name == "eval":
            tier = assess_command(" ".join(args)).tier
            return tier, "eval runs a built command"
        return CommandTier.WORKSPACE_WRITE, "sources a script"
    if name == "xargs":
        return _classify_wrapped_command(args)
    if name == "find":
        return _classify_find(args)
    if name == "sed":
        if any(
            arg in {"-i", "--in-place"} or arg.startswith("-i")
            for arg in args
        ):
            return CommandTier.WORKSPACE_WRITE, "sed edits files in place"
        return CommandTier.READ_ONLY, "sed prints to stdout"
    if name == "awk":
        if "system(" in segment:
            return CommandTier.DESTRUCTIVE, "awk calls system()"
        return CommandTier.READ_ONLY, "awk prints to stdout"
    if name == "tar":
        if any(arg in {"-x", "-c", "--extract", "--create"} for arg in args):
            return CommandTier.WORKSPACE_WRITE, "tar writes files"
        return CommandTier.READ_ONLY, "tar lists an archive"
    if name in {"curl", "wget"}:
        if any(
            arg in {"-o", "-O", "-J", "--output", "--remote-name"}
            or arg.startswith("--output=")
            for arg in args
        ):
            return CommandTier.WORKSPACE_WRITE, f"{name} writes a file"
        return CommandTier.READ_ONLY, f"{name} prints to stdout"
    if name in _TEST_BINARIES:
        if name in {"black", "prettier", "ruff"} and any(
            arg in {"--write", "--fix"} or arg == "format" for arg in args
        ):
            return CommandTier.WORKSPACE_WRITE, f"`{name}` rewrites files"
        return CommandTier.READ_ONLY, f"`{name}` checks only"
    if name == "tsc":
        if "--noEmit" in args:
            return CommandTier.READ_ONLY, "tsc type check"
        return CommandTier.WORKSPACE_WRITE, "tsc emits files"
    if _is_info_invocation(args):
        return CommandTier.READ_ONLY, f"`{name}` prints version/help"
    if name in _READ_ONLY_BINARIES:
        return CommandTier.READ_ONLY, f"`{name}` reads only"
    if name in _WRITE_BINARIES:
        return CommandTier.WORKSPACE_WRITE, f"`{name}` writes to the workspace"

    return (
        CommandTier.WORKSPACE_WRITE,
        f"`{name}` is not a known read-only command",
    )


def _classify_git(args: list[str]) -> tuple[CommandTier, str]:
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}:
            index += 2
            continue
        if arg.startswith("--") and arg != "--no-pager":
            index += 1
            continue
        break
    if index >= len(args):
        return CommandTier.READ_ONLY, "git with no subcommand"

    sub = args[index]
    rest = args[index + 1 :]

    if sub == "rm":
        return CommandTier.BLOCKED, "`git rm` deletes files"
    if sub in {"push", "publish"}:
        return CommandTier.DESTRUCTIVE, "`git push` publishes to a remote"
    if sub == "reset":
        return CommandTier.DESTRUCTIVE, "`git reset` can discard work"
    if sub == "clean":
        if any(arg in {"-n", "--dry-run"} for arg in rest):
            return CommandTier.READ_ONLY, "`git clean --dry-run`"
        return CommandTier.DESTRUCTIVE, "`git clean` deletes untracked files"
    if sub in {"rebase", "filter-branch", "filter-repo"}:
        return CommandTier.DESTRUCTIVE, f"`git {sub}` rewrites history"
    if sub == "branch":
        if any(
            arg in {"-d", "-D", "--delete", "-m", "-M", "--move"}
            for arg in rest
        ):
            return CommandTier.DESTRUCTIVE, "`git branch` deletes or renames"
        return CommandTier.READ_ONLY, "`git branch` lists branches"
    if sub == "tag":
        if any(arg in {"-d", "--delete"} for arg in rest):
            return CommandTier.DESTRUCTIVE, "`git tag -d` deletes a tag"
        if not rest or any(arg in {"-l", "--list"} for arg in rest):
            return CommandTier.READ_ONLY, "`git tag` lists tags"
        return CommandTier.WORKSPACE_WRITE, "`git tag` creates a tag"
    if sub == "checkout":
        if "--" in rest or (rest and rest[0] == "."):
            return (
                CommandTier.DESTRUCTIVE,
                "`git checkout -- .` discards changes",
            )
        return (
            CommandTier.WORKSPACE_WRITE,
            "`git checkout` changes the workspace",
        )
    if sub == "restore":
        return CommandTier.DESTRUCTIVE, "`git restore` discards changes"
    if sub == "stash":
        action = rest[0] if rest else ""
        if action in {"drop", "clear"}:
            return CommandTier.DESTRUCTIVE, "`git stash drop` deletes work"
        if action in {"list", "show"}:
            return CommandTier.READ_ONLY, f"`git stash {action}`"
        return CommandTier.WORKSPACE_WRITE, "`git stash` changes local state"
    if sub == "remote":
        if rest and rest[0] in {"-v", "show", "get-url"}:
            return CommandTier.READ_ONLY, "`git remote` inspection"
        return CommandTier.WORKSPACE_WRITE, "`git remote` changes config"
    if sub == "config":
        if rest and rest[0] in {"--get", "--get-all", "--list", "-l"}:
            return CommandTier.READ_ONLY, "`git config` read"
        return CommandTier.WORKSPACE_WRITE, "`git config` writes config"
    if sub in {
        "status",
        "diff",
        "log",
        "show",
        "blame",
        "grep",
        "describe",
        "rev-parse",
        "ls-files",
        "ls-tree",
        "show-ref",
        "cat-file",
        "merge-base",
        "diff-tree",
        "shortlog",
        "reflog",
        "whatchanged",
    }:
        return CommandTier.READ_ONLY, f"`git {sub}` reads only"
    if sub in {
        "add",
        "commit",
        "init",
        "switch",
        "merge",
        "pull",
        "fetch",
        "clone",
        "mv",
        "cherry-pick",
        "revert",
        "apply",
        "am",
        "submodule",
        "worktree",
        "notes",
    }:
        return (
            CommandTier.WORKSPACE_WRITE,
            f"`git {sub}` changes the workspace",
        )
    return (
        CommandTier.WORKSPACE_WRITE,
        f"`git {sub}` is not known to be read-only",
    )


def _classify_node_tool(
    name: str, args: list[str]
) -> tuple[CommandTier, str]:
    if not args:
        return CommandTier.READ_ONLY, f"`{name}` with no arguments"
    if _is_info_invocation(args):
        return CommandTier.READ_ONLY, f"`{name}` version"
    sub = args[0]
    if sub in {"test", "t"}:
        return CommandTier.READ_ONLY, f"`{name} test`"
    if sub in {"run", "run-script"}:
        script = args[1] if len(args) > 1 else ""
        if script in _TEST_SCRIPTS or script.startswith(
            ("test", "lint", "typecheck", "type-check", "check")
        ):
            return CommandTier.READ_ONLY, f"`{name} run {script}`"
        return CommandTier.WORKSPACE_WRITE, f"`{name} run {script}` may write"
    if sub == "publish":
        return (
            CommandTier.DESTRUCTIVE,
            f"`{name} publish` publishes a package",
        )
    if sub in {"exec", "dlx", "x"}:
        return _classify_wrapped_command(args[1:])
    if sub in {
        "install",
        "i",
        "ci",
        "add",
        "update",
        "up",
        "upgrade",
        "dedupe",
        "prune",
        "uninstall",
        "remove",
        "rm",
        "link",
        "rebuild",
    }:
        return (
            CommandTier.WORKSPACE_WRITE,
            f"`{name} {sub}` changes dependencies",
        )
    if sub in {"ls", "list", "view", "info", "outdated", "why", "audit"}:
        return CommandTier.READ_ONLY, f"`{name} {sub}` reads only"
    return CommandTier.WORKSPACE_WRITE, f"`{name} {sub}` may write"


def _classify_python(
    args: list[str], segment: str = ""
) -> tuple[CommandTier, str]:
    if args and args[0] == "-m":
        module = args[1] if len(args) > 1 else ""
        if module in _PYTHON_TEST_MODULES:
            return (
                CommandTier.READ_ONLY,
                f"`python -m {module}` checks only",
            )
        return CommandTier.WORKSPACE_WRITE, f"`python -m {module}` may write"
    if args and args[0] in _INLINE_PYTHON_FLAGS:
        if _INLINE_PROCESS_SPAWN.search(segment):
            return (
                CommandTier.DESTRUCTIVE,
                "runs inline Python that can start another process",
            )
        return CommandTier.WORKSPACE_WRITE, "runs inline Python"
    if _is_info_invocation(args):
        return CommandTier.READ_ONLY, "python version"
    if args:
        return CommandTier.WORKSPACE_WRITE, "runs a Python script"
    return CommandTier.READ_ONLY, "python with no arguments"


def _classify_node(
    args: list[str], segment: str = ""
) -> tuple[CommandTier, str]:
    if not args:
        return CommandTier.READ_ONLY, "node with no arguments"
    if _is_info_invocation(args):
        return CommandTier.READ_ONLY, "node version"
    if args[0] == "--check":
        return CommandTier.READ_ONLY, "node syntax check"
    if args[0] in _INLINE_NODE_FLAGS:
        if _INLINE_PROCESS_SPAWN.search(segment):
            return (
                CommandTier.DESTRUCTIVE,
                "runs inline JavaScript that can start another process",
            )
        return CommandTier.WORKSPACE_WRITE, "runs inline JavaScript"
    return CommandTier.WORKSPACE_WRITE, "runs a JavaScript script"


def _classify_packages(
    name: str, args: list[str]
) -> tuple[CommandTier, str]:
    sub = args[0] if args else ""
    if sub in {"list", "show", "freeze", "check", "tree"}:
        return CommandTier.READ_ONLY, f"`{name} {sub}` reads only"
    if sub in {
        "install",
        "add",
        "sync",
        "lock",
        "update",
        "upgrade",
        "remove",
        "uninstall",
    }:
        return (
            CommandTier.WORKSPACE_WRITE,
            f"`{name} {sub}` changes dependencies",
        )
    if name == "uv" and sub == "run":
        inner = [arg for arg in args[1:] if not arg.startswith("-")]
        if inner:
            return _classify_command(
                _binary(inner[0]), inner[1:], " ".join(inner)
            )
        return CommandTier.WORKSPACE_WRITE, "`uv run` may write"
    return CommandTier.WORKSPACE_WRITE, f"`{name} {sub}` may write"


def _classify_build(name: str, args: list[str]) -> tuple[CommandTier, str]:
    sub = args[0] if args else ""
    if name == "cargo" and sub == "publish":
        return CommandTier.DESTRUCTIVE, "`cargo publish` publishes a crate"
    if sub in {"test", "check", "clippy", "vet", "fmt"}:
        if name == "cargo" and sub == "fmt" and "--check" not in args:
            return CommandTier.WORKSPACE_WRITE, "`cargo fmt` rewrites files"
        return CommandTier.READ_ONLY, f"`{name} {sub}` checks only"
    return (
        CommandTier.WORKSPACE_WRITE,
        f"`{name} {sub}` writes build output",
    )


def _classify_docker(args: list[str]) -> tuple[CommandTier, str]:
    sub = args[0] if args else ""
    if sub in {"ps", "images", "logs", "inspect", "version", "info", "stats"}:
        return CommandTier.READ_ONLY, f"`docker {sub}` reads only"
    if sub in {"push", "rm", "rmi", "prune"}:
        return (
            CommandTier.DESTRUCTIVE,
            f"`docker {sub}` removes or publishes",
        )
    if sub == "system" and len(args) > 1 and args[1] == "prune":
        return CommandTier.DESTRUCTIVE, "`docker system prune` deletes data"
    return CommandTier.WORKSPACE_WRITE, f"`docker {sub}` changes containers"


def _classify_shell(name: str, args: list[str]) -> tuple[CommandTier, str]:
    index = _shell_command_index(args)
    if index is not None:
        inner = " ".join(args[index + 1 :])
        if inner:
            return (
                assess_command(inner).tier,
                f"`{name} -c` runs a nested command",
            )
        return (
            CommandTier.DESTRUCTIVE,
            f"`{name} -c` reads commands from stdin",
        )
    script = next((arg for arg in args if not arg.startswith("-")), "")
    if script:
        return CommandTier.WORKSPACE_WRITE, f"`{name}` runs a script"
    return CommandTier.DESTRUCTIVE, f"`{name}` reads commands from stdin"


def _classify_powershell(args: list[str]) -> tuple[CommandTier, str]:
    for flag in ("-Command", "-c"):
        if flag in args:
            index = args.index(flag)
            inner = " ".join(args[index + 1 :])
            return assess_command(inner).tier, "PowerShell -Command"
    return CommandTier.WORKSPACE_WRITE, "PowerShell script"


def _classify_cmd(args: list[str]) -> tuple[CommandTier, str]:
    for flag in ("/c", "/C", "/k", "/K"):
        if flag in args:
            index = args.index(flag)
            inner = " ".join(args[index + 1 :])
            return assess_command(inner).tier, "cmd /c"
    return CommandTier.WORKSPACE_WRITE, "cmd script"


def _classify_wrapped_command(args: list[str]) -> tuple[CommandTier, str]:
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 1
    if index >= len(args):
        return CommandTier.WORKSPACE_WRITE, "wrapped command is unknown"
    inner = args[index:]
    return _classify_command(_binary(inner[0]), inner[1:], " ".join(inner))


def _find_exec_tokens(tokens: list[str]) -> list[str]:
    """Tokens of a `find -exec` payload, without `{}` / `;` placeholders."""
    return [token for token in tokens if token not in _FIND_EXEC_TOKENS]


def _classify_find(args: list[str]) -> tuple[CommandTier, str]:
    for index, arg in enumerate(args):
        if arg == "-delete":
            return CommandTier.BLOCKED, "`find -delete` removes files"
        if arg in _FIND_EXEC_FLAGS:
            inner = _find_exec_tokens(args[index + 1 :])
            if inner:
                tier, reason = _classify_command(
                    _binary(inner[0]), inner[1:], " ".join(inner)
                )
                if tier > CommandTier.READ_ONLY:
                    return tier, f"`find -exec`: {reason}"
    return CommandTier.READ_ONLY, "`find` reads only"
