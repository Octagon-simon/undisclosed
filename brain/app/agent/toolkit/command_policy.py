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

import re
import shlex
from dataclasses import dataclass
from enum import IntEnum

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

_WRITE_REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>"})

_DEV_NULL_TARGETS = frozenset({"/dev/null", "nul", "$null"})


def assess_command(command: str | None) -> CommandAssessment:
    """Classify a command line, taking the highest tier of its segments."""
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


def is_blocked(command: str | None) -> bool:
    """True when the command contains a tier 3 action."""
    return assess_command(command).blocked


def describe_tier(tier: CommandTier) -> str:
    """Short label used in tool results and the approval card."""
    return {
        CommandTier.READ_ONLY: "Read only",
        CommandTier.WORKSPACE_WRITE: "Writes files",
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
    }[scope]


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

    if name == "git":
        return _git_scopes(positional)
    if name in {"npm", "pnpm", "yarn", "bun"}:
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
    if name in {"python", "python3"}:
        return _python_scopes(args)
    if name in _READ_BINARIES:
        return (CommandScope.FILE_READS,)
    if name in _WRITE_BINARIES:
        return (CommandScope.FILE_WRITES,)
    if tier == CommandTier.READ_ONLY:
        return (CommandScope.FILE_READS,)
    if tier == CommandTier.WORKSPACE_WRITE:
        return (CommandScope.FILE_WRITES,)
    return ()


def _shell_inner(args: list[str]) -> str:
    for index, arg in enumerate(args):
        if arg == "-c" and index + 1 < len(args):
            return args[index + 1]
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


def _python_scopes(args: list[str]) -> tuple[CommandScope, ...]:
    for index, arg in enumerate(args):
        if arg == "-m" and index + 1 < len(args):
            module = args[index + 1].lower()
            if module in _PYTHON_TEST_MODULES:
                return (CommandScope.BUILDS_TESTS,)
            return (CommandScope.FILE_WRITES,)
    return (CommandScope.FILE_WRITES,)


def _split_segments(command: str) -> list[str]:
    """Split on shell control operators, respecting quotes.

    Newlines separate commands too, so a multi-line script cannot hide a
    blocked command after a harmless first line.
    """
    segments: list[str] = []
    buf: list[str] = []
    quote: str | None = None
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
    if name == "git":
        return _classify_git(args)

    if name in {"npm", "pnpm", "yarn", "bun"}:
        return _classify_node_tool(name, args)
    if name == "npx":
        return _classify_wrapped_command(args)
    if name in {"python", "python3", "py"}:
        return _classify_python(args)
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


def _classify_python(args: list[str]) -> tuple[CommandTier, str]:
    if args and args[0] == "-m":
        module = args[1] if len(args) > 1 else ""
        if module in _PYTHON_TEST_MODULES:
            return (
                CommandTier.READ_ONLY,
                f"`python -m {module}` checks only",
            )
        return CommandTier.WORKSPACE_WRITE, f"`python -m {module}` may write"
    if args and args[0] in {"-c", "-"}:
        return CommandTier.WORKSPACE_WRITE, "inline Python can write"
    if args and args[0] in {"-V", "--version", "-h", "--help"}:
        return CommandTier.READ_ONLY, "python version"
    if args:
        return CommandTier.WORKSPACE_WRITE, "runs a Python script"
    return CommandTier.READ_ONLY, "python with no arguments"


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
    if "-c" in args:
        index = args.index("-c")
        inner = " ".join(args[index + 1 :])
        return (
            assess_command(inner).tier,
            f"`{name} -c` runs a nested command",
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


def _classify_find(args: list[str]) -> tuple[CommandTier, str]:
    for index, arg in enumerate(args):
        if arg == "-delete":
            return CommandTier.BLOCKED, "`find -delete` removes files"
        if arg in {"-exec", "-execdir", "-ok", "-okdir"}:
            inner = []
            for token in args[index + 1 :]:
                if token in {"{}", ";", "+", "\\;"}:
                    continue
                inner.append(token)
            if inner:
                tier, reason = _classify_command(
                    _binary(inner[0]), inner[1:], " ".join(inner)
                )
                if tier >= CommandTier.DESTRUCTIVE:
                    return tier, f"`find -exec`: {reason}"
    return CommandTier.READ_ONLY, "`find` reads only"
