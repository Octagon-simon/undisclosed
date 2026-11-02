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

"""Project understanding via repomix, plus a per-file fingerprint store.

Gives the agent a compact, AI-friendly digest of the current project's codebase
(structure + key code, tree-sitter compressed) so it can understand the repo in
one call instead of many grep/file searches.

Alongside the digest, every source file gets a content hash and a signature-only
structural fingerprint (definition names, arity, return types, imports). The
store lives under ~/.undisclosed/project-context/<workspace>/fingerprints.json
and is what decides whether a cached digest is still valid: a comment-only
commit reuses the cache, a body change does not. It also lets the agent ask
"what actually changed?" and get cosmetic vs structural, instead of re-reading
the whole repo.

Uses `npx repomix` (no install/setup); FAIL-SOFT — if repomix/npx isn't available
the tool returns a clear note so the agent falls back to normal search.

The same import graph can be written to a committable `knowledge-graph.json`
(nodes with dependencies, layers, a 20-file tour, and docstring summaries for the
100 most load-bearing files):

    python -m app.agent.toolkit.project_context_toolkit --write-graph

`--check` exits 1 when the code digest no longer matches, so CI can flag a stale
graph without re-reading the committed one.
"""

import ast
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from camel.toolkits import FunctionTool

from app.agent.toolkit.abstract_toolkit import AbstractToolkit
from app.service.task import Agents

logger = logging.getLogger("project_context_toolkit")

# Cap the digest we return so it never blows the context window. repomix
# --compress already trims heavily; this is a final safety bound.
_MAX_DIGEST_CHARS = 60_000


def _context_root() -> Path:
    return Path.home() / ".undisclosed" / "project-context"


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


# --- fingerprint store -------------------------------------------------------

_FP_VERSION = 3
_FP_MAX_FILES = 3000
_FP_MAX_FILE_BYTES = 2_000_000
_FP_MAX_SYMBOLS = 80
_FP_MAX_IMPORTS = 60
# Parsing and the python-side tree walk are the expensive part, so only real
# source files get a structural fingerprint. Bigger files (minified bundles,
# generated code) are still content-hashed, just in the cheap shallow mode.
_FP_PARSE_MAX_BYTES = 500_000
_FP_MAX_NODES = 120_000
_FP_SCAN_BUDGET_S = 10.0
# on a big repo the first scan runs out of time and leaves text-only entries;
# later scans spend this much upgrading them to structural fingerprints
_FP_DEEPEN_BUDGET_S = 3.0

_LEVEL_ARCHITECTURE = "ARCHITECTURE"
_LEVEL_FULL = "FULL"
_LEVEL_PARTIAL = "PARTIAL"
_LEVEL_ORDER = (_LEVEL_ARCHITECTURE, _LEVEL_FULL, _LEVEL_PARTIAL)

_SKIP_DIR_NAMES = frozenset(
    {
        "node_modules",
        ".git",
        "venv",
        "__pycache__",
        ".venv",
        "site-packages",
        "dist",
        "build",
        "coverage",
        ".next",
        ".turbo",
        "storybook-static",
        "dist-signed",
        "out",
        "release",
        "target",
    }
)
_IMPORT_TYPE_HINTS = (
    "import",
    "use_declaration",
    "include",
    "using_directive",
    "package_clause",
)
_CLASS_NODE_TYPES = frozenset(
    {
        "class_definition",
        "class_declaration",
        "class_body",
        "impl_item",
        "trait_item",
        "interface_declaration",
    }
)
_DOCSTRING_BLOCK_TYPES = frozenset({"module", "block"})


def _workspace_key(workdir: str) -> str:
    return hashlib.sha256(workdir.encode("utf-8")).hexdigest()[:16]


def _store_file(workdir: str) -> Path:
    return _context_root() / _workspace_key(workdir) / "fingerprints.json"


def _digest_paths(workdir: str) -> tuple[Path, Path]:
    base = _context_root() / _workspace_key(workdir)
    return base / "digest.md", base / "digest.key"


def _sha(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8", "replace")
    return hashlib.sha256(data).hexdigest()


def _norm(text: str, limit: int = 120) -> str:
    return " ".join(text.split())[:limit]


def _node_text(node: Any) -> str:
    try:
        return node.text.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def _parse_ts(path: Path):
    """(parser, language, lang) reusing CodeQueryToolkit's grammar table."""
    try:
        from app.agent.toolkit import code_query_toolkit as cq

        lang = cq._lang_for(path)
        if not lang or not cq._HAS_TS:
            return None, None, lang
        return cq.get_parser(lang), cq.get_language(lang), lang
    except Exception:  # noqa: BLE001
        return None, None, None


def _is_python_docstring(node: Any) -> bool:
    parent = node.parent
    if parent is None:
        return False
    # tree-sitter-python hangs the string straight off module/block; older
    # grammars wrap it in an expression_statement. Accept both shapes.
    if parent.type == "expression_statement":
        block, target = parent.parent, parent
    elif parent.type in _DOCSTRING_BLOCK_TYPES:
        block, target = parent, node
    else:
        return False
    if block is None or block.type not in _DOCSTRING_BLOCK_TYPES:
        return False
    for i in range(block.child_count):
        child = block.child(i)
        if child.is_named:
            return child.id == target.id
    return False


def _code_digest(root: Any, lang: str | None) -> str | None:
    """Hash the token stream with comments (and python docstrings) removed.

    Returns None once the node budget is exhausted, so a pathological file can
    never stall the scan; callers then fall back to a text hash.
    """
    python = lang == "python"
    parts: list[str] = []
    stack = [root]
    visited = 0
    while stack:
        cur = stack.pop()
        visited += 1
        if visited > _FP_MAX_NODES:
            return None
        kind = cur.type
        if "comment" in kind:
            continue
        if python and kind == "string" and _is_python_docstring(cur):
            continue
        if cur.child_count == 0:
            text = _node_text(cur).strip()
            if text:
                parts.append(text)
            continue
        for i in range(cur.child_count - 1, -1, -1):
            stack.append(cur.child(i))
    return _sha("\n".join(parts))


def _class_ancestors(node: Any) -> list[str]:
    parts: list[str] = []
    cur = node.parent
    while cur is not None:
        if cur.type in _CLASS_NODE_TYPES:
            name_node = cur.child_by_field_name("name")
            if name_node is not None:
                parts.append(_norm(_node_text(name_node), 60))
        cur = cur.parent
    parts.reverse()
    return parts


def _surface(
    root: Any, language: Any, lang: str
) -> tuple[list[str], list[str]]:
    """Signature-only view of a file: definitions and imports, no bodies."""
    try:
        from app.agent.toolkit import code_query_toolkit as cq

        defs = list(cq._iter_defs(language, root, lang))
    except Exception:  # noqa: BLE001
        return [], []
    symbols: set[str] = set()
    seen: set[int] = set()
    for node in defs:
        if node.id in seen:
            continue
        seen.add(node.id)
        name_node = node.child_by_field_name("name")
        if name_node is None:
            continue
        name = _norm(_node_text(name_node), 60)
        if not name:
            continue
        params = node.child_by_field_name("parameters")
        arity = 0
        if params is not None:
            arity = sum(
                1
                for i in range(params.child_count)
                if params.child(i).is_named
            )
        ret = ""
        for field in ("return_type", "result", "type"):
            ret_node = node.child_by_field_name(field)
            if ret_node is not None:
                ret = _norm(_node_text(ret_node), 60)
                break
        exported = (
            "export "
            if node.parent is not None
            and node.parent.type == "export_statement"
            else ""
        )
        qualified = ".".join([*_class_ancestors(node), name])
        suffix = f" -> {ret}" if ret else ""
        symbols.add(f"{exported}{node.type}:{qualified}({arity}){suffix}")
        if len(symbols) >= _FP_MAX_SYMBOLS:
            break
    imports: set[str] = set()
    for i in range(root.child_count):
        child = root.child(i)
        if not child.is_named:
            continue
        if any(hint in child.type for hint in _IMPORT_TYPE_HINTS):
            text = _norm(_node_text(child), 120)
            if text:
                imports.add(text)
    return sorted(symbols)[:_FP_MAX_SYMBOLS], sorted(imports)[:_FP_MAX_IMPORTS]


def _fingerprint_file(path: Path, deep: bool = True) -> dict | None:
    """Content + structure hashes for one file, or None if it can't be read.

    ``deep=False`` (used once a scan runs out of time) records only the content
    hash, so the file still gets change detection without any parsing.
    """
    try:
        # stat before reading: a write during the read leaves a newer mtime behind
        st = path.stat()
        if st.st_size > _FP_MAX_FILE_BYTES:
            return None
        data = path.read_bytes()
        if len(data) != st.st_size:
            st = path.stat()
            if st.st_size != len(data):
                return None
    except Exception:  # noqa: BLE001
        return None
    fp: dict = {
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "content": _sha(data),
        "code": "",
        "symbols": [],
        "imports": [],
    }
    parser, language, lang = _parse_ts(path)
    if (
        deep
        and parser is not None
        and language is not None
        and lang
        and len(data) <= _FP_PARSE_MAX_BYTES
    ):
        try:
            root = parser.parse(data).root_node
            code = _code_digest(root, lang)
            if code is not None:
                fp["code"] = code
                fp["symbols"], fp["imports"] = _surface(root, language, lang)
                return fp
        except Exception:  # noqa: BLE001
            logger.debug(
                "fingerprint parse failed for %s", path, exc_info=True
            )
    # no grammar, too big, or over the node budget: whitespace-normalised text,
    # so comments count as code and the change level can only be conservative
    text = data.decode("utf-8", "replace")
    fp["code"] = _sha(
        "\n".join(ln.strip() for ln in text.splitlines() if ln.strip())
    )
    # "budget" means the caller had no time left, so a later scan can deepen it;
    # "static" means parsing will never succeed, so stop retrying
    fp["shallow"] = "budget" if not deep else "static"
    return fp


def _prune_gitignored(found: list[Path], workdir: str) -> list[Path]:
    """Drop build output and vendored bundles that git already ignores."""
    if not found or not (Path(workdir) / ".git").exists():
        return found
    try:
        proc = subprocess.run(
            ["git", "-C", workdir, "check-ignore", "--stdin", "-z"],
            input="\0".join(str(p) for p in found),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:  # noqa: BLE001
        return found
    if proc.returncode != 0 or not proc.stdout:
        return found
    ignored = {p for p in proc.stdout.split("\0") if p}
    if not ignored:
        return found
    return [p for p in found if str(p) not in ignored]


def _iter_source_files(workdir: str) -> tuple[list[Path], bool]:
    try:
        from app.agent.toolkit import code_query_toolkit as cq

        exts = set(cq._SUPPORTED_EXT)
    except Exception:  # noqa: BLE001
        return [], False
    found: list[Path] = []
    truncated = False
    for dirpath, dirnames, filenames in os.walk(workdir):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d.lower() not in _SKIP_DIR_NAMES
            and not d.startswith(".")
            and not d.endswith(".app")
        )
        for name in sorted(filenames):
            if Path(name).suffix.lower() not in exts:
                continue
            path = Path(dirpath) / name
            if path.is_symlink():
                continue
            found.append(path)
            if len(found) >= _FP_MAX_FILES:
                truncated = True
                return _prune_gitignored(found, workdir), truncated
    return _prune_gitignored(found, workdir), truncated


def _classify(path: str, prev: dict | None, cur: dict) -> dict | None:
    if prev is None:
        return {
            "path": path,
            "level": _LEVEL_ARCHITECTURE,
            "status": "added",
            "added": list(cur.get("symbols") or [])[:3],
            "removed": [],
        }
    if prev.get("content") == cur.get("content"):
        return None
    if prev.get("code") == cur.get("code"):
        return {
            "path": path,
            "level": _LEVEL_PARTIAL,
            "status": "cosmetic",
            "added": [],
            "removed": [],
        }
    if prev.get("shallow") or cur.get("shallow"):
        # content-only entry: the text hash counts comments, so the change has
        # to be reported conservatively rather than guessed as cosmetic
        return {
            "path": path,
            "level": _LEVEL_FULL,
            "status": "body",
            "added": [],
            "removed": [],
        }
    old_symbols = set(prev.get("symbols") or [])
    new_symbols = set(cur.get("symbols") or [])
    old_imports = set(prev.get("imports") or [])
    new_imports = set(cur.get("imports") or [])
    if old_symbols != new_symbols or old_imports != new_imports:
        return {
            "path": path,
            "level": _LEVEL_ARCHITECTURE,
            "status": "structural",
            "added": sorted(new_symbols - old_symbols),
            "removed": sorted(old_symbols - new_symbols),
            "imports_changed": old_imports != new_imports,
        }
    return {
        "path": path,
        "level": _LEVEL_FULL,
        "status": "body",
        "added": [],
        "removed": [],
    }


def _scan(
    workdir: str, previous: dict[str, dict], converge: bool = False
) -> tuple[dict[str, dict], list[dict], dict]:
    """Fingerprint every source file, reusing unchanged entries by mtime+size."""
    paths, truncated = _iter_source_files(workdir)
    root = Path(workdir).resolve()
    current: dict[str, dict] = {}
    changes: list[dict] = []
    deadline = time.monotonic() + _FP_SCAN_BUDGET_S
    for path in paths:
        try:
            rel = str(path.resolve().relative_to(root)).replace(os.sep, "/")
        except ValueError:
            continue
        prev = previous.get(rel)
        try:
            st = path.stat()
        except OSError:
            continue
        if (
            prev
            and prev.get("size") == st.st_size
            and prev.get("mtime_ns") == st.st_mtime_ns
        ):
            current[rel] = prev
            continue
        fp = _fingerprint_file(path, deep=time.monotonic() < deadline)
        if fp is None:
            continue
        current[rel] = fp
        change = _classify(rel, prev, fp)
        if change is not None:
            changes.append(change)
    # second pass: spend leftover time turning text-only entries into structural
    # ones, newest scan first, so a cold start converges after a couple of calls
    upgrade_deadline = time.monotonic() + _FP_DEEPEN_BUDGET_S
    for rel, fp in list(current.items()):
        reason = fp.get("shallow")
        if not reason or reason == "static":
            continue
        if not converge and time.monotonic() >= upgrade_deadline:
            break
        deeper = _fingerprint_file(root / rel, deep=True)
        # a real attempt records the true reason, so an unparseable file stops
        # costing a re-read on every later scan
        if deeper is not None:
            current[rel] = deeper
    for rel in previous.keys() - current.keys():
        changes.append(
            {
                "path": rel,
                "level": _LEVEL_ARCHITECTURE,
                "status": "deleted",
                "added": [],
                "removed": list(previous[rel].get("symbols") or [])[:3],
            }
        )
    changes.sort(key=lambda c: (_LEVEL_ORDER.index(c["level"]), c["path"]))
    return current, changes, {"files": len(current), "truncated": truncated}


def _load_store(workdir: str) -> tuple[dict, dict[str, dict]]:
    try:
        raw = json.loads(_store_file(workdir).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}, {}
    if not isinstance(raw, dict) or raw.get("version") != _FP_VERSION:
        return {}, {}
    files = raw.get("files")
    if not isinstance(files, dict):
        return raw, {}
    return raw, {k: v for k, v in files.items() if isinstance(v, dict)}


def _save_store(workdir: str, files: dict[str, dict], head: str) -> None:
    path = _store_file(workdir)
    payload = {
        "version": _FP_VERSION,
        "scanned_at": int(time.time()),
        "head": head,
        "files": files,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / f"{path.name}.tmp"
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        # atomic replace; a concurrent scan just overwrites with an equally good baseline
        tmp.replace(path)
    except Exception:  # noqa: BLE001
        logger.debug("failed to save fingerprint store", exc_info=True)


def _digest_key(files: dict[str, dict]) -> str:
    """Cache key over code hashes only, so comment edits keep the cache warm."""
    payload = "\n".join(
        f"{rel}:{fp.get('code') or fp.get('content', '')}"
        for rel, fp in sorted(files.items())
    )
    return _sha(payload)[:16]


def _read_cached_digest(workdir: str, key: str) -> str | None:
    digest_path, key_path = _digest_paths(workdir)
    try:
        if key_path.read_text(encoding="utf-8").strip() != key:
            return None
        return digest_path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return None


def _write_cached_digest(workdir: str, key: str, digest: str) -> None:
    digest_path, key_path = _digest_paths(workdir)
    try:
        digest_path.parent.mkdir(parents=True, exist_ok=True)
        digest_path.write_text(digest, encoding="utf-8")
        key_path.write_text(key, encoding="utf-8")
    except Exception:  # noqa: BLE001
        logger.debug("failed to cache project digest", exc_info=True)


def _touched_count(workdir: str, files: dict[str, dict]) -> int:
    """Cheap stat-only check: how many indexed files moved since the scan."""
    root = Path(workdir).resolve()
    count = 0
    for rel, fp in files.items():
        try:
            st = (root / rel).stat()
        except OSError:
            count += 1
            continue
        if st.st_size != fp.get("size") or st.st_mtime_ns != fp.get(
            "mtime_ns"
        ):
            count += 1
    return count


# --- dependency graph / read order -------------------------------------------

_PY_FROM_RE = re.compile(r"^\s*from\s+(\.*)([\w.]*)\s+import\b")
_PY_IMPORT_RE = re.compile(r"^\s*import\s+([\w.]+)")
_JS_SPEC_RE = re.compile(r"""(?:\bfrom|\brequire\()\s*["']([^"']+)["']""")
_JS_EXTS = ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
_JS_INDEX = ("/index.ts", "/index.tsx", "/index.js", "/index.jsx")
_JS_LANGS = frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"})
_ENTRY_STEMS = frozenset({"main", "app", "cli", "index", "server", "manage"})
_TEST_PATH_RE = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_|\.(test|spec)\.")
_ORDER_CACHE: dict[str, list[dict]] = {}
_ORDER_CACHE_MAX = 4


def _resolve_python(rel: str, statement: str, keys: dict[str, str]) -> str | None:
    """Repo-relative path imported by one python import statement."""
    match = _PY_FROM_RE.match(statement)
    if match and match.group(1):
        base = rel.rsplit("/", 1)[0] if "/" in rel else ""
        for _ in range(len(match.group(1)) - 1):
            base = base.rsplit("/", 1)[0] if "/" in base else ""
        module = match.group(2).replace(".", "/")
        target = f"{base}/{module}".strip("/")
        return keys.get(target) or keys.get(f"{target}/__init__")
    if match:
        target = match.group(2).replace(".", "/")
    else:
        match = _PY_IMPORT_RE.match(statement)
        if not match:
            return None
        target = match.group(1).replace(".", "/")
    # absolute import: the package root may sit above the workspace root, so try
    # the full spec and then every shorter suffix of it
    parts = target.split("/")
    for i in range(len(parts)):
        candidate = "/".join(parts[i:])
        hit = keys.get(candidate) or keys.get(f"{candidate}/__init__")
        if hit:
            return hit
    return None


_TSCONFIG_NAMES = ("tsconfig.json", "jsconfig.json")
_JSONC_BLOCK_RE = re.compile(r"/\*.*?\*/", re.S)
_JSONC_LINE_RE = re.compile(r"(^|[^:\\])//[^\n]*")
_JSONC_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _load_jsonc(path: Path) -> dict[str, Any]:
    """tsconfig/jsconfig parsed with comments and trailing commas allowed."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    text = _JSONC_BLOCK_RE.sub("", text)
    text = _JSONC_LINE_RE.sub(r"\1", text)
    text = _JSONC_TRAILING_COMMA_RE.sub(r"\1", text)
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _compiler_options(config: Path, depth: int = 0) -> dict[str, Any]:
    """Merged compilerOptions, following relative ``extends`` chains."""
    data = _load_jsonc(config)
    merged: dict[str, Any] = {}
    parent = data.get("extends")
    if isinstance(parent, str) and parent.startswith(".") and depth < 4:
        base = (config.parent / parent).resolve()
        if base.suffix != ".json":
            base = base.with_suffix(".json")
        if base.is_file():
            merged.update(_compiler_options(base, depth + 1))
    options = data.get("compilerOptions")
    if isinstance(options, dict):
        merged.update(options)
    return merged


def _as_repo_path(path: Path, root: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(root)
    except (OSError, ValueError):
        return None
    return rel.as_posix()


def _compile_aliases(config: Path, root: Path) -> list[tuple[str, str, str, bool]]:
    """(prefix, suffix, repo-relative target, is_wildcard) for one tsconfig."""
    options = _compiler_options(config)
    paths = options.get("paths")
    if not isinstance(paths, dict) or not paths:
        return []
    base_url = options.get("baseUrl")
    base_dir = config.parent / base_url if isinstance(base_url, str) else config.parent
    aliases: list[tuple[str, str, str, bool]] = []
    for pattern, targets in paths.items():
        if not isinstance(pattern, str) or not isinstance(targets, list):
            continue
        for target in targets:
            if not isinstance(target, str):
                continue
            wildcard = "*" in pattern and "*" in target
            if wildcard:
                prefix, _, pattern_tail = pattern.partition("*")
                target_head, _, target_tail = target.partition("*")
                repo_target = _as_repo_path(base_dir / target_head, root)
                if repo_target is None:
                    continue
                aliases.append((prefix, pattern_tail, repo_target, True))
            else:
                repo_target = _as_repo_path(base_dir / target, root)
                if repo_target is None:
                    continue
                aliases.append((pattern, "", repo_target, False))
    # longest prefix first so a specific alias wins over a broad one
    aliases.sort(key=lambda a: -len(a[0]))
    return aliases


def _aliases_for(rel: str, root: Path, cache: dict[str, list]) -> list:
    """Path aliases from the tsconfig/jsconfig nearest to this file."""
    directory = rel.rsplit("/", 1)[0] if "/" in rel else ""
    if directory in cache:
        return cache[directory]
    aliases: list[tuple[str, str, str, bool]] = []
    probe = (root / directory) if directory else root
    while True:
        for name in _TSCONFIG_NAMES:
            config = probe / name
            if config.is_file():
                aliases = _compile_aliases(config, root)
                break
        if aliases or probe == root:
            break
        if root not in probe.parents:
            break
        probe = probe.parent
    cache[directory] = aliases
    return aliases


def _probe_module(joined: str, rel_set: set[str]) -> str | None:
    for suffix in _JS_EXTS:
        if f"{joined}{suffix}" in rel_set:
            return f"{joined}{suffix}"
    for index in _JS_INDEX:
        if f"{joined}{index}" in rel_set:
            return f"{joined}{index}"
    return None


def _resolve_js(
    rel: str,
    statement: str,
    rel_set: set[str],
    aliases: list[tuple[str, str, str, bool]] | None = None,
) -> str | None:
    """Repo-relative path imported by one JS/TS import statement."""
    match = _JS_SPEC_RE.search(statement)
    if not match:
        return None
    spec = match.group(1)
    if spec.startswith("."):
        base = rel.rsplit("/", 1)[0] if "/" in rel else ""
        joined = os.path.normpath(os.path.join(base, spec)).replace(os.sep, "/")
        return _probe_module(joined, rel_set)
    for prefix, suffix, target, wildcard in aliases or ():
        if wildcard:
            if not spec.startswith(prefix) or not spec.endswith(suffix):
                continue
            if len(spec) < len(prefix) + len(suffix):
                continue
            rest = spec[len(prefix) : len(spec) - len(suffix)]
            joined = f"{target}/{rest}" if rest else target
        elif spec == prefix:
            joined = target
        else:
            continue
        hit = _probe_module(os.path.normpath(joined).replace(os.sep, "/"), rel_set)
        if hit:
            return hit
    return None


def _dependency_graph(
    files: dict[str, dict],
    root: Path | None = None,
) -> tuple[dict[str, set[str]], dict[str, int]]:
    """Import edges between indexed files, plus each file's importer count."""
    keys: dict[str, str] = {}
    for rel in files:
        if Path(rel).suffix.lower() != ".py":
            continue
        # a workspace can nest the package root (brain/app/... imported as
        # app...), so register every suffix of the module path
        parts = rel.rsplit(".", 1)[0].split("/")
        for i in range(len(parts)):
            keys.setdefault("/".join(parts[i:]), rel)
    rel_set = set(files)
    alias_cache: dict[str, list] = {}
    deps: dict[str, set[str]] = {rel: set() for rel in files}
    for rel, fingerprint in files.items():
        suffix = Path(rel).suffix.lower()
        if suffix != ".py" and suffix not in _JS_LANGS:
            continue
        for statement in fingerprint.get("imports") or []:
            try:
                if suffix == ".py":
                    hit = _resolve_python(rel, statement, keys)
                else:
                    aliases = (
                        _aliases_for(rel, root, alias_cache) if root else None
                    )
                    hit = _resolve_js(rel, statement, rel_set, aliases)
            except Exception:  # noqa: BLE001
                hit = None
            if hit and hit != rel:
                deps[rel].add(hit)
    fan_in = {rel: 0 for rel in files}
    for source, targets in deps.items():
        if _is_test_path(source):
            continue  # a test importing a module says nothing about importance
        for target in targets:
            fan_in[target] += 1
    return deps, fan_in


def _depths(deps: dict[str, set[str]]) -> dict[str, int]:
    """Longest dependency chain under each file (cycles count as a broken edge)."""
    depth: dict[str, int] = {}
    state: dict[str, int] = {}  # 1 = on the stack, 2 = settled
    for start in deps:
        if state.get(start):
            continue
        stack: list[tuple[str, bool]] = [(start, False)]
        while stack:
            node, settled = stack.pop()
            if settled:
                state[node] = 2
                kids = [k for k in deps.get(node, ()) if state.get(k) == 2]
                depth[node] = 1 + max((depth[k] for k in kids), default=-1)
                continue
            if state.get(node):
                continue
            state[node] = 1
            stack.append((node, True))
            for child in deps.get(node, ()):
                if not state.get(child):
                    stack.append((child, False))
    return depth


def read_order(workdir: str, limit: int | None = 15) -> list[dict]:
    """Indexed files ranked by how load-bearing they are.

    Each row carries ``path``, ``depth`` (longest chain of intra-project
    imports below it), ``deps``, ``fan_in``, ``entry`` and ``score``
    (``fan_in + depth``). Tests are excluded. Returns an empty list until a
    fingerprint scan has run.
    """
    _, files = _load_store(workdir)
    if not files:
        return []
    key = f"{_workspace_key(workdir)}:{_digest_key(files)}:{limit}"
    cached = _ORDER_CACHE.get(key)
    if cached is not None:
        return cached
    deps, fan_in = _dependency_graph(files, Path(workdir).resolve())
    depth = _depths(deps)
    rows = []
    for rel in files:
        # tests always sit at the top of any depth ranking (they import the
        # deepest module) and reading them first teaches nothing
        if _is_test_path(rel):
            continue
        row_depth = depth.get(rel, 0)
        row_fan_in = fan_in.get(rel, 0)
        rows.append(
            {
                "path": rel,
                "depth": row_depth,
                "deps": len(deps.get(rel) or ()),
                "fan_in": row_fan_in,
                "entry": Path(rel).stem.lower() in _ENTRY_STEMS,
                # load-bearing (many importers) and deep (pulls in many layers)
                # are both reasons to read a file early
                "score": row_fan_in + row_depth,
            }
        )
    rows.sort(key=lambda r: (-r["score"], -r["fan_in"], r["path"]))
    if limit is not None:
        rows = rows[:limit]
    if len(_ORDER_CACHE) >= _ORDER_CACHE_MAX:
        _ORDER_CACHE.pop(next(iter(_ORDER_CACHE)))
    _ORDER_CACHE[key] = rows
    return rows


def _is_test_path(rel: str) -> bool:
    return bool(_TEST_PATH_RE.search(rel))


def _count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _format_read_order(rows: list[dict]) -> str:
    if not rows:
        return ""
    lines = [
        "Read order (ranked by importers + dependency depth: foundation first, "
        "then the layers built on it):"
    ]
    for i, row in enumerate(rows, 1):
        tags = [_count(row["deps"], "dep")]
        if row["fan_in"]:
            tags.append(f"imported by {row['fan_in']}")
        if row["entry"]:
            tags.insert(0, "entry")
        lines.append(f"  {i}. {row['path']}  ({', '.join(tags)})")
    return "\n".join(lines) + "\n\n"


# --- knowledge graph artifact -------------------------------------------------

_GRAPH_VERSION = 1
_GRAPH_SUMMARY_CHARS = 220
_GRAPH_MAX_SYMBOLS = 8
_GRAPH_MAX_SUMMARY_BYTES = 400_000
_JS_LEADING_BLOCK_RE = re.compile(r"\A\s*/\*(.*?)\*/", re.S)
_JS_LEADING_LINES_RE = re.compile(r"\A((?:\s*//[^\n]*\n)+)")


def _python_summary(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        doc = ast.get_docstring(ast.parse(text))
    except Exception:  # noqa: BLE001
        return None
    return _trim_summary(doc)


def _js_summary(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    block = _JS_LEADING_BLOCK_RE.match(text)
    if block:
        body = " ".join(
            line.strip().lstrip("*").strip() for line in block.group(1).splitlines()
        )
        return _trim_summary(body)
    lines = _JS_LEADING_LINES_RE.match(text)
    if lines:
        body = " ".join(
            line.strip().lstrip("/").strip() for line in lines.group(1).splitlines()
        )
        return _trim_summary(body)
    return None


def _trim_summary(text: str | None) -> str | None:
    if not text:
        return None
    flat = " ".join(text.split())
    if len(flat) < 8:
        return None
    if len(flat) > _GRAPH_SUMMARY_CHARS:
        flat = flat[: _GRAPH_SUMMARY_CHARS - 1].rstrip() + "…"
    return flat


def _file_summary(path: Path) -> str | None:
    try:
        if path.stat().st_size > _GRAPH_MAX_SUMMARY_BYTES:
            return None
    except OSError:
        return None
    if path.suffix.lower() == ".py":
        return _python_summary(path)
    if path.suffix.lower() in _JS_LANGS:
        return _js_summary(path)
    return None


def build_knowledge_graph(
    workdir: str,
    summary_limit: int = 100,
    include_symbols: bool = True,
) -> dict[str, Any]:
    """Node/edge/layer snapshot of the workspace, stable enough to commit.

    Every list is sorted by path and every node is emitted on its own line, so
    regenerating after a one-file change touches one line of the file.
    """
    # scan from disk, not from the store: a concurrent session may have saved a
    # fingerprint for a file whose mtime+size it saw before an in-place edit, and
    # the artifact must describe the tree as it is
    files, _, stats = _scan(workdir, {}, converge=True)
    _save_store(workdir, files, _git_head(workdir))
    root = Path(workdir).resolve()
    deps, fan_in = _dependency_graph(files, root)
    depth = _depths(deps)
    scores = {rel: fan_in[rel] + depth.get(rel, 0) for rel in files}
    ranked = sorted(files, key=lambda r: (-scores[r], r))
    summarised = {
        rel for rel in ranked[:summary_limit] if not _is_test_path(rel)
    }

    nodes = []
    for rel in sorted(files):
        node: dict[str, Any] = {
            "path": rel,
            "lang": Path(rel).suffix.lstrip("."),
            "fan_in": fan_in[rel],
            "depth": depth.get(rel, 0),
            "deps": sorted(deps[rel]),
        }
        if Path(rel).stem.lower() in _ENTRY_STEMS:
            node["entry"] = True
        if include_symbols and rel in summarised:
            symbols = (files[rel].get("symbols") or [])[:_GRAPH_MAX_SYMBOLS]
            if symbols:
                node["symbols"] = symbols
        if rel in summarised:
            summary = _file_summary(root / rel)
            if summary:
                node["summary"] = summary
        nodes.append(node)

    layers = []
    tops = {rel.split("/", 1)[0] if "/" in rel else "(root)" for rel in files}
    for top in sorted(tops):
        if top == "(root)":
            members = [rel for rel in files if "/" not in rel]
        else:
            members = [rel for rel in files if rel.split("/", 1)[0] == top]
        if len(members) < 3:
            continue
        entry_points = sorted(
            (rel for rel in members if Path(rel).stem.lower() in _ENTRY_STEMS),
            # deep pulls the app in; barrels are deep too but are not entries
            key=lambda r: (
                Path(r).stem.lower() == "index",
                -depth.get(r, 0),
                r,
            ),
        )[:3]
        layers.append(
            {
                "name": top,
                "files": len(members),
                "internal_edges": sum(
                    1
                    for rel in members
                    for dep in deps[rel]
                    if (dep.split("/", 1)[0] if "/" in dep else "(root)") == top
                ),
                "entry_points": entry_points,
            }
        )

    return {
        "version": _GRAPH_VERSION,
        "commit": _git_head(workdir),
        "scan_version": _FP_VERSION,
        "code_digest": _digest_key(files),
        "files": stats["files"],
        "truncated": stats["truncated"],
        "layers": layers,
        "tour": [
            {
                "path": rel,
                "score": scores[rel],
                "fan_in": fan_in[rel],
                "deps": len(deps[rel]),
            }
            for rel in ranked[:20]
        ],
        "nodes": nodes,
    }


def _dump_graph(graph: dict[str, Any]) -> str:
    """JSON with one node per line, so a diff stays readable."""
    head = {k: v for k, v in graph.items() if k != "nodes"}
    body = json.dumps(head, indent=2).rstrip()
    if body.endswith("}"):
        body = body[:-1].rstrip()
    rows = ",\n".join(
        f"    {json.dumps(node, separators=(', ', ': '))}" for node in graph["nodes"]
    )
    return f'{body},\n  "nodes": [\n{rows}\n  ]\n}}\n'


def write_knowledge_graph(
    workdir: str,
    out: Path | None = None,
    summary_limit: int = 100,
    include_symbols: bool = True,
) -> Path:
    """Write the graph to ``out`` (default: knowledge-graph.json at the root)."""
    target = out or (Path(workdir) / "knowledge-graph.json")
    graph = build_knowledge_graph(workdir, summary_limit, include_symbols)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_dump_graph(graph), encoding="utf-8")
    return target


def graph_staleness(workdir: str, out: Path | None = None) -> tuple[bool, list[str]]:
    """Whether the committed graph lags the code, and why.

    Compares the digest of the indexed code hashes, not git history: a
    comment-only edit leaves the graph valid, and an uncommitted edit still
    counts, which is what a pre-commit check needs.
    """
    source = out or (Path(workdir) / "knowledge-graph.json")
    try:
        graph = json.loads(source.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return True, ["knowledge-graph.json missing or unreadable"]
    recorded = graph.get("code_digest")
    if not isinstance(recorded, str) or not recorded:
        return True, ["knowledge-graph.json has no code digest"]
    if graph.get("scan_version") != _FP_VERSION:
        return True, ["fingerprint scan version changed since the graph was built"]
    # same source of truth as the writer: a fresh scan of the tree
    files, _, _ = _scan(workdir, {}, converge=True)
    if _digest_key(files) == recorded:
        return False, []
    return True, [
        f"code changed since the graph was built "
        f"(graph: {graph.get('files')} files, now: {len(files)})"
    ]


def _format_staleness(workdir: str, out: Path | None) -> str:
    stale, moved = graph_staleness(workdir, out)
    if not stale:
        return "knowledge-graph.json is up to date."
    lines = ["knowledge-graph.json is stale:"]
    lines += [f"  {item}" for item in moved]
    lines.append(
        "Regenerate with: python -m app.agent.toolkit.project_context_toolkit "
        "--write-graph"
    )
    return "\n".join(lines)


def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Write or check the committed knowledge-graph.json artifact."
    )
    parser.add_argument("--workdir", default=".", help="workspace root (default: cwd)")
    parser.add_argument("--out", default=None, help="output path")
    parser.add_argument(
        "--write-graph", action="store_true", help="regenerate knowledge-graph.json"
    )
    parser.add_argument(
        "--check", action="store_true", help="exit 1 if the graph lags the tree"
    )
    parser.add_argument(
        "--summary-limit",
        type=int,
        default=100,
        help="how many load-bearing files get a summary and symbols (0 disables)",
    )
    parser.add_argument(
        "--no-symbols", action="store_true", help="omit symbol names from nodes"
    )
    args = parser.parse_args(argv)
    workdir = str(Path(args.workdir).resolve())
    out = Path(args.out).expanduser() if args.out else None
    if not Path(workdir).is_dir():
        print(f"not a directory: {workdir}")
        return 2
    if args.write_graph:
        target = write_knowledge_graph(
            workdir, out, max(args.summary_limit, 0), not args.no_symbols
        )
        print(f"wrote {target} ({target.stat().st_size // 1024}KB)")
        return 0
    if args.check:
        stale, _ = graph_staleness(workdir, out)
        print(_format_staleness(workdir, out))
        return 1 if stale else 0
    parser.print_help()
    return 0


def _human_age(seconds: int) -> str:
    if seconds < 120:
        return f"{seconds}s"
    if seconds < 7200:
        return f"{seconds // 60}m"
    if seconds < 172800:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def _changes_prefix(changes: list[dict], stats: dict) -> str:
    if not changes:
        if not stats.get("files"):
            return ""
        return "(fingerprints: no known file changed since the last scan)\n\n"
    counts = {level: 0 for level in _LEVEL_ORDER}
    for change in changes:
        counts[change["level"]] += 1
    parts = ", ".join(
        f"{counts[level]} {level.lower()}"
        for level in _LEVEL_ORDER
        if counts[level]
    )
    top = ", ".join(
        f"{change['path']} ({change['level'].lower()})"
        for change in changes[:5]
    )
    more = " ..." if len(changes) > 5 else ""
    return (
        f"(fingerprints: {len(changes)} files changed since the last scan: "
        f"{parts}. {top}{more})\n\n"
    )


def _format_changes(changes: list[dict], stats: dict, meta: dict) -> str:
    if not changes:
        return (
            f"Nothing changed since the last scan "
            f"({stats['files']} source files indexed)."
        )
    when = "the last scan"
    scanned_at = meta.get("scanned_at")
    if isinstance(scanned_at, (int, float)):
        age = max(0, int(time.time() - scanned_at))
        when = f"the scan {_human_age(age)} ago"
    labels = {
        _LEVEL_ARCHITECTURE: (
            "ARCHITECTURE: names, parameters, return types or imports changed; "
            "re-read these"
        ),
        _LEVEL_FULL: (
            "FULL: bodies changed; any summary you hold for these files is stale"
        ),
        _LEVEL_PARTIAL: (
            "PARTIAL: comments, docstrings or whitespace only; summaries still hold"
        ),
    }
    buckets = {
        level: [c for c in changes if c["level"] == level]
        for level in _LEVEL_ORDER
    }
    lines = [
        f"{len(changes)} files changed since {when} "
        f"({stats['files']} source files indexed):"
    ]
    for level in _LEVEL_ORDER:
        items = buckets[level]
        if not items:
            continue
        lines.append("")
        lines.append(f"{labels[level]} ({len(items)})")
        for change in items[:20]:
            detail = ""
            added = change.get("added") or []
            removed = change.get("removed") or []
            if added:
                detail += "  +" + ", ".join(added[:3])
            if removed:
                detail += "  -" + ", ".join(removed[:3])
            if change.get("imports_changed"):
                detail += "  imports changed"
            if change.get("status") == "deleted":
                detail += "  (deleted)"
            lines.append(f"  {change['path']}{detail}")
        if len(items) > 20:
            lines.append(f"  +{len(items) - 20} more")
    if stats.get("truncated"):
        lines.append(f"\n(scan capped at {_FP_MAX_FILES} files)")
    return "\n".join(lines)


class ProjectContextToolkit(AbstractToolkit):
    """`understand_project` and `project_changes` over the open workspace."""

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

    def _skeleton_change_hint(self) -> str:
        """Stat-only freshness line for the skeleton map (no scan, no parse)."""
        workdir = self.working_directory
        if not workdir:
            return ""
        _, previous = _load_store(workdir)
        if not previous:
            return ""
        touched = _touched_count(workdir, previous)
        if not touched:
            return (
                "(fingerprints: no known file changed since the last scan)\n\n"
            )
        return (
            f"(fingerprints: {touched} of {len(previous)} indexed files changed "
            f"since the last scan; call project_changes() to split cosmetic from "
            f"structural)\n\n"
        )

    def _ensure_store(self) -> None:
        """Index the workspace once so the read order has an import graph."""
        workdir = self.working_directory
        if not workdir:
            return
        _, files = _load_store(workdir)
        if files:
            return
        current, _, _ = _scan(workdir, {})
        _save_store(workdir, current, _git_head(workdir))

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
                    f"to read any symbol body on demand)\n\n"
                    f"{self._skeleton_change_hint()}{map_text}"
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "skeleton map failed, falling back to digest: %s", exc
            )
        # Tree-sitter unavailable or empty workspace — fall back to the dense
        # repomix digest (full=True) so the agent still gets whole-repo
        # orientation. No recursion because full=True bypasses this branch.
        return self.understand_project(full=True)

    def _repomix_digest(
        self, workdir: str, focus: str | None = None
    ) -> tuple[str | None, bool, str]:
        """Run repomix and return (digest, truncated, error)."""
        if shutil.which("npx") is None:
            return (
                None,
                False,
                "Could not build a project digest (npx/repomix unavailable). "
                "Fall back to the normal file/search tools.",
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
                None,
                False,
                "Could not build a project digest (repomix failed). Fall back "
                "to the normal file/search tools.",
            )
        digest = (proc.stdout or "").strip()
        if not digest:
            return (
                None,
                False,
                "The project digest came back empty. Fall back to the normal "
                "file/search tools.",
            )
        truncated = len(digest) > _MAX_DIGEST_CHARS
        return digest[:_MAX_DIGEST_CHARS], truncated, ""

    @staticmethod
    def _truncation_note(truncated: bool) -> str:
        if not truncated:
            return ""
        return (
            "\n\n[Digest truncated - call understand_project(focus=...) to zoom "
            "into a specific area.]"
        )

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
        dependency-ordered *read order* (the load-bearing files first, ranked by
        how much of the project depends on them) followed by a cheap tree-sitter
        *skeleton map* (~1.5k tokens) — module/class/function signatures with no
        bodies — so the agent learns *where* things live before reading them. Use
        ``context_at`` to fetch the exact slice of any symbol the skeleton points
        at. This replaces the old behavior of always
        dumping a whole-repo repomix blob into the context window (the primary
        token burner).

        Set ``full=True`` (or pass ``focus=``) to get the dense repomix digest
        for rare whole-repo orientation needs. That path is cached against
        per-file code fingerprints, so a comment-only commit reuses it while a
        body change regenerates it; the returned text starts with a count of
        what changed since the last scan (``project_changes`` has the detail).

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
            self._ensure_store()
            order = _format_read_order(read_order(workdir))
            return f"{order}{self._skeleton_map()}"

        # Focused subsets are cheap, never cached, and never touch the store.
        if focus:
            digest, truncated, error = self._repomix_digest(workdir, focus)
            if digest is None:
                return error
            return f"{digest}{self._truncation_note(truncated)}"

        _, previous = _load_store(workdir)
        current, changes, stats = _scan(workdir, previous)
        cache_key = _digest_key(current)
        prefix = _changes_prefix(changes, stats)

        # Keyed by per-file code hashes, not git HEAD: a comment-only commit
        # keeps the digest warm, a body or signature change regenerates it.
        if not refresh:
            cached = _read_cached_digest(workdir, cache_key)
            if cached is not None:
                _save_store(workdir, current, _git_head(workdir))
                return f"(cached project digest, code unchanged)\n\n{prefix}{cached}"

        digest, truncated, error = self._repomix_digest(workdir)
        if digest is None:
            return error
        _write_cached_digest(workdir, cache_key, digest)
        _save_store(workdir, current, _git_head(workdir))
        return f"{prefix}{digest}{self._truncation_note(truncated)}"

    def project_changes(self) -> str:
        """Report what changed in the workspace since the last fingerprint scan.

        Compares per-file content and structure hashes and sorts every change
        into ARCHITECTURE (names, parameters, return types or imports moved),
        FULL (a body changed, so any summary you hold is stale), or PARTIAL
        (comments, docstrings or whitespace only). Use it after a cold start or
        when ``understand_project`` says files changed, instead of re-reading
        the repo. It also advances the stored baseline, so a repeat call with
        no edits reports that nothing changed.

        Returns:
            str: Changed files grouped by how much re-reading they need.
        """
        workdir = self.working_directory
        if not workdir or not Path(workdir).is_dir():
            return (
                "No workspace folder is open, so there's no project to scan. "
                "Use the normal file/search tools instead."
            )
        meta, previous = _load_store(workdir)
        current, changes, stats = _scan(workdir, previous)
        _save_store(workdir, current, _git_head(workdir))
        if not previous:
            return (
                f"No stored fingerprints yet; indexed {stats['files']} source "
                f"files. The next call reports what changed since this scan."
            )
        return _format_changes(changes, stats, meta)

    def get_tools(self) -> list[FunctionTool]:
        return [
            FunctionTool(self.understand_project),
            FunctionTool(self.project_changes),
        ]

    @classmethod
    def toolkit_name(cls) -> str:
        return "Project Context Toolkit"


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
