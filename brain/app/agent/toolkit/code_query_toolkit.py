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

"""Precise code structural queries via tree-sitter.

Companion to the repomix project digest (ProjectContextToolkit). Where repomix
gives the agent broad, orientation-level understanding of the whole repo,
tree-sitter gives exact, surgical answers to questions like: "where is ``Foo``
defined?", "who calls ``bar()``?", "what does this file import?".

FAIL-SOFT — if tree-sitter (or a grammar for the language) isn't available, or a
file can't be parsed, the tools degrade to simple text/GREP-like matching and
return a clear note, so the agent never loses the ability to search. This mirrors
the same philosophy repomix already uses for the project digest.
"""

import logging
import re
from pathlib import Path

from camel.toolkits import FunctionTool

from app.agent.toolkit.abstract_toolkit import AbstractToolkit
from app.service.task import Agents

logger = logging.getLogger("code_query_toolkit")

try:  # native deps — fail-soft if not installed
    from tree_sitter import Node  # noqa: F401  (type only)
    from tree_sitter_language_pack import get_language, get_parser

    _HAS_TS = True
except Exception as exc:  # noqa: BLE001
    logger.warning("tree-sitter unavailable (%s); code_query degrades to grep", exc)
    _HAS_TS = False
    get_parser = None  # type: ignore[assignment]
    get_language = None  # type: ignore[assignment]

# Extensions we know how to parse with tree_sitter_language_pack get_parser().
_SUPPORTED_EXT: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".mjs": "javascript",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".rs": "rust",
    ".java": "java",
    ".go": "go",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".cs": "c_sharp",
}

# Cap on how many matches we return so the agent context never blows up.
_MAX_RESULTS = 200

# Hard char budget for a tool's textual output. If a result stream crosses
# this, the middle is truncated with an explicit marker so the surrounding
# (most relevant) context lines are preserved and the context window is never
# flooded with a huge multi-line result.
_MAX_CONTEXT_CHARS = 4_000

# Node types that introduce a new symbol definition in JS/TS. The base set in
# `_is_definition` covers function/class declarations; modern React/TS code
# relies heavily on this extended set (arrow functions, const/let bindings,
# exported declarations), which the R1 boundary check showed the toolkit was
# blind to. Kept as a frozenset for fast membership tests.
_DEFINITION_NODE_TYPES = frozenset(
    {
        # --- generic / python ---
        "function_definition",
        "class_definition",
        "method_definition",
        "function_declaration",
        "class_declaration",
        "function_declaration",
        # --- C / C++ / Rust ---
        "struct_specifier",
        "enum_specifier",
        "type_alias_declaration",
        "using_declaration",
        # --- JavaScript / TypeScript ---
        "arrow_function",
        "lexical_declaration",
        "variable_declarator",
        "export_statement",
        # --- Java / Go / Kotlin ---
        "method_declaration",
        "function_declaration",
        "class_declaration",
    }
)


def _lang_for(path: Path) -> str | None:
    return _SUPPORTED_EXT.get(path.suffix.lower())


def _walk(node) -> object:
    """Yield every descendant node (a generic depth-first traversal)."""
    stack = [node]
    while stack:
        cur = stack.pop()
        yield cur
        # push children in reverse so we visit left-to-right
        for i in range(cur.child_count - 1, -1, -1):
            stack.append(cur.child(i))


# Tree-sitter name-bearing patterns per definition node type. We match both the
# container and (for JS/TS) the inner named binding so a single compiled query
# captures definitions that `_node_name` then resolves. Patterns are aggregated
# into one S-Expression per language family so the engine runs in native C,
# ~10-50x faster than the O(n) Python `_walk` + regex path.
_DEF_QUERY_PATTERNS: dict[str, str] = {
    "python": """
        (function_definition name: (identifier) @n)
        (class_definition name: (identifier) @n)
    """,
    "javascript": """
        (function_declaration name: (identifier) @n)
        (class_declaration name: (type_identifier) @n)
        (method_definition name: (property_identifier) @n)
        (lexical_declaration (variable_declarator name: (identifier) @n))
        (variable_declaration (variable_declarator name: (identifier) @n))
    """,
    "typescript": """
        (function_declaration name: (identifier) @n)
        (class_declaration name: (type_identifier) @n)
        (method_definition name: (property_identifier) @n)
        (lexical_declaration (variable_declarator name: (identifier) @n))
        (variable_declaration (variable_declarator name: (identifier) @n))
        (interface_declaration name: (type_identifier) @n)
        (type_alias_declaration name: (type_identifier) @n)
        (enum_declaration name: (identifier) @n)
    """,
    # JSX/TSX: tree-sitter must use the dedicated `tsx` grammar, else JSX
    # elements (`<div />`) tokenize as generics and the parse errors out,
    # silently swallowing every declaration that follows (e.g. `export
    # function Bar()`). Mirroring the typescript patterns here keeps detection
    # correct for the React/TSX code the agent lives in.
    "tsx": """
        (function_declaration name: (identifier) @n)
        (class_declaration name: (type_identifier) @n)
        (method_definition name: (property_identifier) @n)
        (lexical_declaration (variable_declarator name: (identifier) @n))
        (variable_declaration (variable_declarator name: (identifier) @n))
        (interface_declaration name: (type_identifier) @n)
        (type_alias_declaration name: (type_identifier) @n)
        (enum_declaration name: (identifier) @n)
    """,
    "c": """
        (function_definition declarator: (function_declarator declarator: (identifier) @n))
        (struct_specifier name: (type_identifier) @n)
    """,
    "cpp": """
        (function_definition declarator: (function_declarator declarator: (identifier) @n))
        (struct_specifier name: (type_identifier) @n)
        (class_specifier name: (type_identifier) @n)
    """,
    "rust": """
        (function_item name: (identifier) @n)
        (struct_item name: (type_identifier) @n)
        (type_item name: (type_identifier) @n)
    """,
    "java": """
        (class_declaration name: (identifier) @n)
        (method_declaration name: (identifier) @n)
    """,
    "go": """
        (function_declaration name: (identifier) @n)
        (type_declaration (type_spec name: (type_identifier) @n))
    """,
    "ruby": """
        (method name: (identifier) @n)
        (class name: (constant) @n)
    """,
    "php": """
        (function_definition name: (name) @n)
        (class_declaration name: (name) @n)
    """,
    "swift": """
        (function_declaration name: (simple_identifier) @n)
    """,
    "kotlin": """
        (function_declaration name: (simple_identifier) @n)
        (class_declaration name: (type_identifier) @n)
    """,
    "c_sharp": """
        (class_declaration name: (identifier) @n)
        (method_declaration name: (identifier) @n)
    """,
}

# Per-language import-statement patterns matched by `imports_of`. Each capture
# names the ``@i`` node — the full import statement — so the tool can pull its
# source text directly, in native C, rather than walking the whole CST.
_IMPORT_QUERY_PATTERNS: dict[str, str] = {
    "python": """
        (import_statement) @i
        (import_from_statement) @i
    """,
    "javascript": """
        (import_statement) @i
    """,
    "typescript": """
        (import_statement) @i
    """,
    "c": """
        (preproc_include) @i
    """,
    "cpp": """
        (preproc_include) @i
        (using_declaration) @i
    """,
    "rust": """
        (use_declaration) @i
    """,
    "java": """
        (import_declaration) @i
    """,
    "go": """
        (import_declaration) @i
    """,
    "ruby": """
        (call) @i
    """,
    "swift": """
        (import_declaration) @i
    """,
    "kotlin": """
        (import_header) @i
    """,
    "c_sharp": """
        (using_directive) @i
    """,
}


def _run_captures(language, pattern: str, root, capture_name: str = "n"):
    """Run a compiled tree-sitter S-expression query and yield captured Nodes.

    Returns an iterator of the nodes captured under ``capture_name``. Uses the
    native C query engine via `tree_sitter.Query` + `tree_sitter.QueryCursor`
    (this supports the installed pack, where `Language.query()` does NOT exist
    and `Language.name` is None). Yields nothing on any failure so callers fall
    back to the generic `_walk` path.
    """
    if language is None or not pattern:
        return
    try:  # noqa: PLR5501
        import tree_sitter as _ts

        query = _ts.Query(language, pattern)
        cursor = _ts.QueryCursor(query)
        captures = cursor.captures(root)  # dict: capture_name -> [Node, ...]
        for node in captures.get(capture_name, []):
            yield node
    except Exception:  # noqa: BLE001 — fall to the generic walk
        logger.debug("compiled query failed; falling back to _walk", exc_info=True)
        return


def _def_container(node) -> object:
    """Resolve the *definition container* for a captured node.

    ``_DEF_QUERY_PATTERNS`` capture the NAME node of a definition (the
    ``@n`` position), e.g. for ``(function_definition name: (identifier) @n)``
    the captured node is the bare ``identifier`` ``greet``. Downstream callers
    (`find_symbol`, `file_symbols`, `skeleton_map`) need the whole definition
    node (``function_definition`` / ``class_definition`` / ...) so they can
    read ``node.type``, ``_node_line(node)``, ``_is_top_level(node)`` and
    resolve the name from its ``name`` field.

    Strategy — three cases, in order:
      1. ``node`` is already a definition container with a resolvable name.
      2. ``node`` is a bare name node: walk UP to the nearest ancestor whose
         type is a known definition container (handles identifier -> definition).
      3. ``node`` is a name-bearing container that itself has no ``name`` field
         but wraps a named binding (e.g. ``lexical_declaration`` ->
         ``variable_declarator``): walk DOWN to the innermost named definition.

    Falls back to returning ``node`` unchanged if nothing else resolves.
    """
    if node is None:
        return node
    # Case 1: already a resolvable definition container.
    if node.type in _DEFINITION_NODE_TYPES and _node_name(node):
        return node
    # Case 2: bare name node -> walk up to the nearest definition container.
    cur = node
    while cur is not None:
        if cur.type in _DEFINITION_NODE_TYPES and _node_name(cur):
            return cur
        cur = cur.parent
    # Case 3: a wrapper container (e.g. export_statement / lexical_declaration)
    # that holds a named declaration -> walk down to the innermost named def.
    stack = [node]
    best: object = node
    while stack:
        cur = stack.pop()
        if cur.type in _DEFINITION_NODE_TYPES and _node_name(cur):
            best = cur
            stack.extend(cur.children)  # keep descending toward innermost
    return best


def _iter_def_names(language, root, lang: str | None = None) -> object:
    """Yield (node, name) definition tuples using a compiled s-expression query.

    The compiled patterns capture NAME nodes, so each result is resolved to its
    definition container via ``_def_container`` before being yielded. Falls
    back to `_walk` + `_is_definition` if the grammar lacks a matching pattern,
    so behavior is preserved for unsupported grammars. `language` may be None
    (no tree-sitter) — then nothing is yielded. ``lang`` is the language key
    from ``_lang_for`` (e.g. "typescript"); the tree-sitter ``Language`` object
    does not expose a usable name, so it is threaded in explicitly.
    """
    if language is None:
        return
    qs = _DEF_QUERY_PATTERNS.get(lang or "")
    if qs:
        matched = False
        for captured in _run_captures(language, qs, root):
            node = _def_container(captured)
            nm = _node_name(node) or ""
            if nm:
                yield node, nm
                matched = True
        if matched:
            return
    for node in _walk(root):
        if _is_definition(node):
            nm = _node_name(node) or ""
            if nm:
                yield node, nm


def _iter_defs(language, root, lang: str | None = None) -> object:
    """Yield every definition container node, best-effort fast path.

    Uses the same compiled-name query as `_iter_def_names` but resolves each
    captured name to its container with `_def_container` and yields just the
    node. Falls back to `_walk` + `_is_definition` when no pattern matches."""
    if language is None:
        return
    qs = _DEF_QUERY_PATTERNS.get(lang or "")
    if qs:
        matched = False
        for captured in _run_captures(language, qs, root):
            node = _def_container(captured)
            matched = True
            yield node
        if matched:
            return
    for node in _walk(root):
        if _is_definition(node):
            yield node


def _iter_name_nodes(language, root, name: str) -> object:
    """Yield identifier/attribute nodes whose text equals ``name``.

    Uses a compiled s-expression query for `identifier` nodes when tree-sitter
    is available, otherwise falls back to the generic `_walk`. This is the fast
    path for reference/caller scans.
    """
    if language is None:
        return
    for node in _run_captures(language, "(identifier) @n", root):
        try:
            if node.text.decode("utf-8", errors="replace") == name:
                yield node
        except Exception:  # noqa: BLE001
            continue
    for node in _walk(root):
        if node.type in ("identifier", "attribute", "property_identifier"):
            try:
                if node.text.decode("utf-8", errors="replace") == name:
                    yield node
            except Exception:  # noqa: BLE001
                continue


def _truncate_middle(text: str, budget: int = _MAX_CONTEXT_CHARS) -> str:
    """Trim the *middle* of a multi-line result so the head/tail survive.

    Preserves the first and last ~40% of lines and inserts an explicit marker so
    the truncation is visible to the model (never silently cuts context).
    """
    if len(text) <= budget or "\n" not in text:
        return text
    lines = text.splitlines()
    target = budget // 64  # rough line estimate for the char budget
    if len(lines) <= target:
        return text
    keep_head = max(target // 2, 1)
    keep_tail = max(target // 2, 1)
    hidden = len(lines) - keep_head - keep_tail
    marker = f"\n# ... [{hidden} lines omitted to keep within token budget] ...\n"
    head = lines[:keep_head]
    tail = lines[-keep_tail:] if keep_tail else []
    return "\n".join(head) + marker + "\n".join(tail)


def _node_line(node) -> int | None:
    """1-based start line of a node, if it has one."""
    try:
        return (node.start_point[0] or 0) + 1
    except Exception:  # noqa: BLE001
        return None


def _node_col(node) -> int | None:
    """1-based start column of a node."""
    try:
        return (node.start_point[1] or 0) + 1
    except Exception:  # noqa: BLE001
        return None


def _node_name(node) -> str:
    """Best-effort name of a definition node.

    Handles both `identifier` and `property_identifier` name fields (JS/TS
    methods/classes use property_identifier), plus calls, string keys and
    shorthand so arrow-function and variable_declarator names resolve.
    """
    try:
        n = node.child_by_field_name("name")
        if n is not None:
            if n.type in {"identifier", "property_identifier", "type_identifier",
                          "simple_identifier", "constant"}:
                return n.text.decode("utf-8", errors="replace")
            # e.g. `function foo() {}` keyed via a call in some grammars
            if n.type == "call":
                callee = n.child_by_field_name("function")
                if callee is not None and callee.type == "identifier":
                    return callee.text.decode("utf-8", errors="replace")
        # JS const/let `const a = 1, b = 2;` -> capture each declarator's name.
        if node.type == "variable_declarator":
            vn = node.child_by_field_name("name")
            if vn is not None and vn.type in {
                "identifier", "property_identifier", "type_identifier",
                "simple_identifier", "constant",
            }:
                return vn.text.decode("utf-8", errors="replace")
        if node.type == "arrow_function":
            # `const f = () => ` — the declarator carries the real name.
            return ""
    except Exception:  # noqa: BLE001
        pass
    return ""


def _is_definition(node) -> bool:
    """True when a node introduces a new symbol definition."""
    if node.type in _DEFINITION_NODE_TYPES:
        # JS/TS `export const foo = () => {}`: the export wrapper is a
        # *container* of a declaration, not itself the symbol. We still report
        # it (so find_symbol works on the export) but must walk its children to
        # surface the inner named binding too.
        return True
    # Python-style assignment/parameter defs.
    if node.type in {"assignment", "typed_parameter"}:
        return True
    # A parenthesized arrow between declarators is a container, not a def.
    if node.type == "function":
        return True
    return False


def _grep_definition(path: Path, name: str):
    """Text-based fallback definition search (no tree-sitter needed)."""
    pattern = re.compile(
        rf"[^A-Za-z0-9_.](?:def|class|function|type|struct|public|let|const|var)\s*"
        rf"{re.escape(name)}\b"
    )
    hits = []
    try:
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            if pattern.search(line):
                hits.append(
                    f"{path}:{lineno}:1  {line.strip()[:120]}  [grep fallback]"
                )
    except Exception as exc:  # noqa: BLE001
        logger.debug("grep definition fallback failed for %s: %s", path, exc)
    return hits


def _grep_callers_line(path: Path, name: str) -> list[tuple[int, str]]:
    """Text-based caller fallback: lines mentioning ``name`` attributed to the
    nearest preceding def-like line. Best-effort when tree-sitter is absent."""
    found: list[tuple[int, str]] = []
    def_rx = re.compile(
        r"^\s*(?:def|class|func|function|type|struct)\s+([A-Za-z0-9_]+)"
    )
    current_def: tuple[int, str] | None = None
    try:
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            m = def_rx.match(line)
            if m:
                current_def = (lineno, f"{path}:{lineno}:1  {m.group(1)}")
            if current_def and re.search(rf"\b{re.escape(name)}\b", line):
                found.append(
                    (current_def[0], f"{current_def[1]}  [grep fallback]")
                )
    except Exception:  # noqa: BLE001
        pass
    return found


def _grep_symbols_fallback(path: Path) -> list[str]:
    """Text-based fallback to enumerate symbols (when tree-sitter's missing)."""
    hits = []
    pattern = re.compile(
        r"^\s*(?:def|class|func|function|type|struct|public\s+"
        r"(?:class|func|function|def)|export\s+(?:function|class|const|let|var))"
        r"\s+([A-Za-z0-9_]+)\b"
    )
    try:
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            m = pattern.match(line)
            if m:
                hits.append(f"{path}:{lineno}:1  {m.group(1)}  (grep fallback)")
    except Exception as exc:  # noqa: BLE001
        logger.debug("grep symbols fallback failed: %s", exc)
    return hits


def _grep_imports(path: Path) -> list[str]:
    """Text-based import fallback (when tree-sitter's missing): pull any line
    that looks like an import/require/include/using statement."""
    hits: list[str] = []
    rx = re.compile(
        r"^\s*(?:import|from|using|use|require|include|#\s*include)\b",
        re.IGNORECASE,
    )
    try:
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            if rx.match(line):
                hits.append(f"{path}:{lineno}  {line.strip()[:120]}  [grep fallback]")
    except Exception as exc:  # noqa: BLE001
        logger.debug("grep imports fallback failed: %s", exc)
    return hits


# Node types that open a NESTED scope. A definition is "top-level" only if it is
# NOT inside one of these (except through transparent JS/TS export/declaration
# wrappers handled separately). Used by `skeleton_map` to keep the index to
# module/class/function-level signatures instead of every nested binding.
_SCOPE_NODE_TYPES = frozenset(
    {
        "function_definition", "class_definition",
        "method_definition", "function_declaration", "method_declaration",
        "class_declaration", "class_specifier", "function_item", "struct_item",
        "impl_item", "block", "statement_block", "class_body", "declaration_list",
        "switch_body", "body", "method",
    }
)

# JS/TS containers that merely expose/wrap a top-level declaration without
# opening a new lexical scope — transparent in the top-level check.
_TRANSPARENT_WRAPPER_TYPES = frozenset(
    {
        "export_statement", "lexical_declaration", "variable_declaration",
        "assignment_statement", "expression_statement", "declaration",
        "abstract_class_declaration", "interface_declaration",
        "type_alias_declaration", "enum_declaration",
    }
)


def _is_top_level(node, root) -> bool:
    """True when ``node`` is a top-level (module/namespace) declaration, i.e.
    not nested inside a function/method/class/block body."""
    cur = node.parent
    while cur is not None and cur is not root:
        if cur.type in _SCOPE_NODE_TYPES:
            return False
        cur = cur.parent
    return True


class CodeQueryToolkit(AbstractToolkit):
    """Surgical code queries over the workspace via tree-sitter syntax trees.

    Complements ProjectContextToolkit (the broad repomix digest): use these
    tools when you need an exact answer about a specific symbol, function, or
    file rather than whole-repo orientation.
    """

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

    # ---- helpers -----------------------------------------------------------

    def _resolve_paths(self, paths: list[str] | None) -> list[Path]:
        """Resolve user-specified paths against the working directory. If none
        given, default to the whole workspace (best-effort, bounded)."""
        root = Path(self.working_directory) if self.working_directory else Path.cwd()
        if not root.is_dir():
            root = Path.cwd()
        candidates: list[Path] = []
        explicit = bool(paths)  # caller named paths => honour even unknown ext
        if paths:
            for p in paths:
                expanded = list(root.glob(p))
                candidates.extend(expanded or [root / p])
        else:
            # Default: scan the workspace for supported source files (bounded).
            for pat in (
                "**/*.py", "**/*.js", "**/*.jsx", "**/*.ts", "**/*.tsx",
                "**/*.rs", "**/*.go", "**/*.java", "**/*.rb", "**/*.php",
                "**/*.swift", "**/*.kt", "**/*.cs",
            ):
                matches = [p for p in root.glob(pat) if _lang_for(p)]
                candidates.extend(matches)
        seen: set[Path] = set()
        result: list[Path] = []
        for p in candidates:
            p = p.resolve()
            parts_l = [seg.lower() for seg in p.parts]
            if not p.is_file() or (not explicit and not _lang_for(p)):
                continue
            if any(
                x in parts_l
                for x in (
                    "node_modules", ".git", "venv", "__pycache__", ".venv",
                    "dist", "build", "site-packages",
                )
            ):
                continue
            if p not in seen:
                seen.add(p)
                result.append(p)
        return result[:_MAX_RESULTS]

    def _parse(self, path: Path):
        """Return (parser, language, lang_key, tree) or (None, None, None, None).

        ``lang_key`` is the `_SUPPORTED_EXT` name (e.g. "typescript") used to
        select the query pattern — the tree-sitter ``Language`` object exposes
        no usable name in this install, so we thread the extension-derived key
        through explicitly.
        """
        lang = _lang_for(path)
        if not _HAS_TS or not lang:
            return None, None, None, None
        try:
            parser = get_parser(lang)  # type: ignore[misc]
            language = get_language(lang)  # type: ignore[misc]
            tree = parser.parse(path.read_bytes())
            # Error-tolerant reparse for the TypeScript family. A `.ts` file can
            # legitimately contain JSX (React code lives in `.ts` too), and the
            # dedicated `typescript` grammar tokenises `<div />` as generics,
            # producing an ERROR subtree that swallows every declaration that
            # follows (e.g. `export function Bar()`). The `tsx` grammar is a
            # superset that parses plain TS *and* JSX correctly, so on error we
            # reparse with it and thread the `tsx` lang_key so the query table
            # (and known-good JSX patterns) match.
            if lang in {"typescript", "javascript"} and tree.root_node.has_error:
                # The `tsx` grammar is a superset of the plain grammars and
                # parses JSX plus plain TS/JS correctly. Any parse *errors* in
                # the plain grammar are most likely JSX being tokenised as
                # generics — which silently swallows following declarations. So
                # on error we reparse with `tsx` and prefer its result even if
                # it still carries residual errors (e.g. a trailing incomplete
                # `export interface I`), since it recovers the JSX-adjacent
                # symbols that the plain grammar drops.
                tsx_parser = get_parser("tsx")
                tsx_language = get_language("tsx")
                tsx_tree = tsx_parser.parse(path.read_bytes())
                return tsx_parser, tsx_language, "tsx", tsx_tree
            return parser, language, lang, tree
        except Exception as exc:  # noqa: BLE001
            logger.debug("tree-sitter parse failed for %s: %s", path, exc)
            return None, None, None, None

    # ---- tools -------------------------------------------------------------

    def find_symbol(
        self, name: str, paths: list[str] | None = None
    ) -> str:
        """Find where a symbol (function, class, variable, constant) is
        DEFINED across the given paths (or the whole workspace if omitted).

        Args:
            name (str): The symbol name to search for (case-sensitive).
            paths (list[str] | None): Optional glob(s) or file paths to restrict
                the search, e.g. ['src/**/*.ts'] or ['app/main.py']. Defaults to
                the whole workspace.

        Returns:
            str: File:line:col locations where the symbol is defined, or a note.
        """
        results: list[str] = []
        for path in self._resolve_paths(paths):
            parser, language, lang, tree = self._parse(path)
            if parser is None or tree is None:
                results.extend(_grep_definition(path, name))
                continue
            root = tree.root_node
            for node, _ in _iter_def_names(language, root, lang):
                got = _node_name(node)
                # The query already names it; confirm exact match for `name`.
                if got == name:
                    results.append(
                        f"{path}:{_node_line(node)}:{_node_col(node)}  "
                        f"{name}  ({node.type})"
                    )
                    if len(results) >= _MAX_RESULTS:
                        break
        if not results:
            return f"No definition of `{name}` found."
        return _truncate_middle("Definitions found:\n" + "\n".join(results))

    def file_symbols(self, path: str) -> str:
        """List every definition (function/class/constant) in a file.

        Args:
            path (str): Path to the file (relative to the workspace, or
                absolute). A directory is resolved to the files under it.

        Returns:
            str: A list of symbol names with their line numbers.
        """
        results: list[str] = []
        if Path(path).is_dir():
            files = self._resolve_files_in_dir(path)
        else:
            files = self._resolve_paths([path])
        for f in files:
            parser, language, lang, tree = self._parse(f)
            if parser is None or tree is None:
                results.extend(_grep_symbols_fallback(f))
                continue
            for node, nm in _iter_def_names(language, tree.root_node, lang):
                if nm:
                    results.append(
                        f"{f}:{_node_line(node)}:{_node_col(node)}  {nm}  ({node.type})"
                    )
                    if len(results) >= _MAX_RESULTS:
                        break
        if not results:
            return f"No symbols found in {path}."
        return _truncate_middle(
            f"Symbols in {path}:\n" + "\n".join(sorted(set(results)))
        )

    def _resolve_files_in_dir(self, path: str) -> list[Path]:
        root = Path(self.working_directory) if self.working_directory else Path.cwd()
        p = Path(path).resolve() if Path(path).is_absolute() else (root / path).resolve()
        if p.is_dir():
            return self._resolve_paths([str(p) + "/**/*"])
        return self._resolve_paths([str(p)])

    def find_references(
        self, name: str, paths: list[str] | None = None
    ) -> str:
        """Find every reference (use) of a symbol name across the given paths.

        Note: this is a syntactic match on identifier/attribute nodes — it does
        NOT resolve scopes, so it may include unrelated identifiers with the
        same name in different files. Use ``paths`` to narrow.

        Args:
            name (str): The symbol name to find references to.
            paths (list[str] | None): Optional glob(s)/file paths. Defaults to
                the whole workspace.

        Returns:
            str: File:line:col reference locations, or a note.
        """
        results: list[str] = []
        for path in self._resolve_paths(paths):
            parser, language, lang, tree = self._parse(path)
            if parser is None or tree is None:
                try:
                    for lineno, line in enumerate(
                        path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
                    ):
                        for m in re.finditer(rf"\b{re.escape(name)}\b", line):
                            results.append(
                                f"{path}:{lineno}:{m.start() + 1}  "
                                f"{line.strip()[:120]}  [grep fallback]"
                            )
                            if len(results) >= _MAX_RESULTS:
                                break
                        if len(results) >= _MAX_RESULTS:
                            break
                except Exception:  # noqa: BLE001
                    continue
                continue
            root = tree.root_node
            # Match identifier/attribute nodes whose text equals `name` via a
            # compiled query; early-exit the moment the budget is exhausted
            # instead of materialising every match in the workspace up front.
            for node in _iter_name_nodes(language, root, name):
                results.append(
                    f"{path}:{_node_line(node)}:{_node_col(node)}  {node.type}"
                )
                if len(results) >= _MAX_RESULTS:
                    break
        if not results:
            return f"No references to `{name}` found in the given paths."
        return _truncate_middle(
            f"References to `{name}`:\n" + "\n".join(results)
        )

    def callers_of(
        self, name: str, paths: list[str] | None = None
    ) -> str:
        """Find functions/methods that reference (call or use) ``name``.

        Heuristic: any function/method/class definition whose body contains a
        node named ``name`` (identifier or attribute) is reported as a caller.
        This is syntax-based, not full call-graph analysis.

        Args:
            name (str): The callee symbol to find callers of.
            paths (list[str] | None): Optional glob(s)/file paths. Defaults to
                the whole workspace.

        Returns:
            str: The enclosing definitions that reference ``name`` (deduped).
        """
        found: list[tuple[int, str]] = []
        for path in self._resolve_paths(paths):
            parser, language, lang, tree = self._parse(path)
            if parser is None or tree is None:
                # Grep fallback: any line mentioning `name`, attributed to the
                # nearest enclosing def-like line (best-effort text heuristic).
                found.extend(_grep_callers_line(path, name))
                continue
            root = tree.root_node
            for node in _iter_name_nodes(language, root, name):
                anc = node.parent
                guard = 0
                while anc is not None and guard < 60:
                    guard += 1
                    if _is_definition(anc) or anc.type in {
                        "function_definition", "class_definition",
                        "method_definition", "function_declaration",
                        "method_declaration", "function_item", "impl_item",
                    }:
                        def_label = _node_name(anc) or anc.type
                        found.append(
                            (
                                (_node_line(anc) or 0),
                                f"{path}:{_node_line(anc)}:{_node_col(anc)}  {def_label}",
                            )
                        )
                        break
                    anc = anc.parent
        seen: set[str] = set()
        out: list[str] = []
        for _, label in sorted(found):
            if label not in seen:
                seen.add(label)
                out.append(label)
        if not out:
            return f"No enclosing callers of `{name}` found."
        return _truncate_middle(f"Callers of `{name}`:\n" + "\n".join(out))

    def imports_of(self, path: str) -> str:
        """List every import/using statement at the top of a source file.

        Args:
            path (str): Path to the file (relative or absolute).

        Returns:
            str: The import statements (with line numbers) or a note.
        """
        files = self._resolve_paths([path])
        if not files:
            return f"No source file found at {path}."
        f = files[0]
        parser, language, lang, tree = self._parse(f)
        if parser is None or tree is None:
            # Real grep fallback — asymmetric with the other tools is avoided by
            # returning actual matches instead of just a "can't parse" note.
            fallback = _grep_imports(f)
            if fallback:
                return "Imports in " + path + ":\n" + "\n".join(fallback)
            return f"No source file found at {path} or no imports detected."
        lines: list[str] = []
        root = tree.root_node
        qs = _IMPORT_QUERY_PATTERNS.get(lang) if lang else None
        if qs:
            for node in _run_captures(language, qs, root, capture_name="i"):
                snippet = node.text.decode("utf-8", errors="replace").replace("\n", " ")
                lines.append(f"{f}:{_node_line(node)}  {snippet[:120]}")
                if len(lines) >= _MAX_RESULTS:
                    break
            if lines:
                return f"Imports in {path}:\n" + "\n".join(lines)
        else:
            # Fall back to a generic walk for grammars without a pattern.
            for node in _walk(root):
                t = node.type
                if (
                    t in {
                        "import_statement", "import_from_statement",
                        "using_declaration", "include_declaration",
                        "import_declaration",
                    }
                    or t.startswith("import_statement")
                ):
                    snippet = node.text.decode("utf-8", errors="replace").replace("\n", " ")
                    lines.append(f"{f}:{_node_line(node)}  {snippet[:120]}")
                    if len(lines) >= _MAX_RESULTS:
                        break
        if not lines:
            return f"No import statements found in {path}."
        return f"Imports in {path}:\n" + "\n".join(lines)

    def context_at(
        self, path: str, line: int, radius: int = 5
    ) -> str:
        """Return source code around a specific line in a file.

        Args:
            path (str): Path to the file (relative or absolute).
            line (int): 1-based line number to center on.
            radius (int): Lines of context to include on each side. Defaults 5.

        Returns:
            str: A labelled code excerpt with line numbers.
        """
        files = self._resolve_paths([path])
        if not files:
            return f"No source file found at {path}."
        f = files[0]
        try:
            src_lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception as exc:  # noqa: BLE001
            return f"Could not read {path}: {exc}"
        line = max(line, 1)
        start = max(line - radius, 1)
        end = min(line + radius, len(src_lines))
        pad = len(str(end))
        out = [f"{path}  (lines {start}–{end})", ""]
        for i in range(start, end + 1):
            marker = ">" if i == line else " "
            out.append(f"{marker} {i:>{pad}} | {src_lines[i - 1]}")
        return "\n".join(out)

    def skeleton_map(
        self, paths: list[str] | None = None, max_files: int = 40
    ) -> str:
        """Return a compact Structure-First index of the codebase: file paths,
        module/class names and function/method signatures — WITHOUT bodies.

        This is the cheap orientation map for the agent's context window. It
        costs far less than a full repomix digest (target: well under ~1.5k
        tokens) and is meant to be read FIRST; the agent then uses
        ``context_at`` to fetch only the exact implementation slice it needs
        (Fetch-on-Demand). Use it instead of dumping the whole project when you
        want to locate *where* something lives before reading its body.

        Args:
            paths (list[str] | None): Optional glob(s) to restrict, e.g.
                ['src/**/*.ts']. Defaults to the whole workspace scope.
            max_files (int): Upper bound on files scanned so the map stays tiny.

        Returns:
            str: A hierarchical skeleton map (files + top-level signatures).
        """
        if max_files > 100:
            max_files = 100  # hard safety bound — the map must stay small
        files = self._resolve_paths(paths)[:max_files]
        if not files:
            return "No source files to index for a skeleton map."
        out: list[str] = []
        # Resolve the workspace root the same way `_resolve_paths` does so the
        # rel-path math is stable on macOS (where tmp dirs resolve to /private/).
        work_root = Path(self.working_directory).resolve() if self.working_directory else Path.cwd()
        for f in files:
            rel = f.relative_to(work_root)
            out.append(f"## {rel}")
            parser, language, lang, tree = self._parse(f)
            if parser is None or tree is None:
                # grep fallback: surfaces the same signature-level shape.
                for hit in _grep_symbols_fallback(f):
                    out.append(f"   {hit}")
                continue
            # One line per top-level definition (name + line) — no bodies.
            for node, nm in _iter_def_names(language, tree.root_node, lang):
                # Only surface top-level declarations (module/class/function
                # level), not nested binds in function/class bodies, so the map
                # stays a skeleton and every line remains scannable.
                if not _is_top_level(node, tree.root_node):
                    continue
                out.append(
                    f"   {nm}  ({node.type}, line {_node_line(node)})"
                )
        return _truncate_middle("Structure-First skeleton map:\n" + "\n".join(out))

    def get_tools(self) -> list[FunctionTool]:
        return [
            FunctionTool(self.find_symbol),
            FunctionTool(self.file_symbols),
            FunctionTool(self.find_references),
            FunctionTool(self.callers_of),
            FunctionTool(self.imports_of),
            FunctionTool(self.context_at),
            FunctionTool(self.skeleton_map),
        ]
    @classmethod
    def toolkit_name(cls) -> str:
        return "Code Query Toolkit"
