# Tree-sitter: precise code queries

**Problem.** The agent's only fast way to answer "where is `Foo` defined?" or "who
calls `bar()`?" was grep or RAG over text. Both are guesses: they match comments,
strings, and substrings, and they cannot tell a definition from a mention. For a
coding agent that reads and edits a real workspace, that leads to wrong files,
dead-end searches, and wasted tool calls.

**Solution.** Add a tree-sitter-backed `code_query` toolkit that gives the agent
*structural* answers from a parsed concrete syntax tree (CST), alongside (not
replacing) the existing whole-repo `understand_project` digest.

Status: **implemented** (the plan's "R1", commit series around 2026-09-01). The
frontend/editor tree-sitter track ("R2") was deliberately not started.

---

## Why not just use repomix for everything

The repo already had `understand_project`, which shells out to
`npx repomix --compress --stdout`, truncates to 60k chars, and caches the digest
per project (keyed on workdir + git HEAD). That is excellent for *broad
orientation*: one compressed blob the LLM can read.

But the two tools answer different questions:

| Axis | repomix (broad digest) | tree-sitter (structural) |
| --- | --- | --- |
| Whole-repo orientation | Strong | Weak (it is a parser, not a summarizer) |
| "Where is X defined?" | Weak (text) | Strong (exact node) |
| Call sites / references | Not native | Strong (query the CST) |
| Enclosing function at line N | No | Yes (`context_at`) |
| Error tolerance on partial code | Skips unparseable | Yields a usable tree |
| Natural language for the LLM | Native | You must render it |

So repomix produces *semantic context a model can read*; tree-sitter produces
*syntax a program can query*. They are complementary. The full rationale is in
[docs/reviews/project-context-tree-sitter.md](../reviews/project-context-tree-sitter.md).

---

## How it works

**Module:** `brain/app/agent/toolkit/code_query_toolkit.py`

`CodeQueryToolkit` lazy-loads `tree_sitter_language_pack` and maps file extensions
to grammars (`.py` → python, `.ts/.tsx` → typescript, `.js` → javascript,
`.json`, `.go`, `.java`, `.rs`, and so on). It exposes read-only tools:

| Tool | Purpose |
| --- | --- |
| `find_symbol(name)` | Exact definition locations (file/line/range) from the CST, not regex hits in comments or strings. |
| `find_references(name)` | Real usage/call sites from the CST. |
| `callers_of(function_name)` | Enclosing functions that call a given function (call-graph via a CST query). |
| `imports_of(path)` | Import/require statements of a file. |
| `context_at(path, line)` | The enclosing top-level definition containing `line`, returned as a bounded source slice. |
| `file_symbols(path)` | An outline of one file (functions/classes/variables). |

**Wiring:** `brain/app/agent/factory/toolkit_assembler.py` builds it behind the
`code_query` config flag (enabled by default). It is registered in
`brain/app/agent/tool_rag.py::_CORE_TOOLKIT_MARKERS` as `"code query"`, so its
tools are always reachable and never filtered out by per-turn tool selection
(the same treatment as `understand_project`).

**Dependencies** are in `brain/pyproject.toml`: `tree-sitter`,
`tree-sitter-language-pack` (bundles ~100 compiled grammars), `tree-sitter-python`.

---

## Design rules (the fail-soft philosophy)

- If the language pack or a grammar is unavailable, or the file's language is
  unsupported, **fall back to grep** and say so. Never raise into a turn.
- Returned context is capped (`_MAX_CONTEXT_CHARS`, ~8k) so one answer cannot blow
  the context window.
- Every method is **read-only**, so it needs no governance/approval gating
  (unlike `file_write` or `terminal`).

---

## The frontend track we did not do (R2)

The original plan also proposed using tree-sitter inside Theia/Monaco for
incremental, error-tolerant highlighting, semantic outline, and folding. That is
the bigger, editor-quality track and was intentionally left out. If you pick it
up, read
[docs/plans/tree-sitter-implementation-plan.md](../plans/tree-sitter-implementation-plan.md)
section "R2" first: it lists the dependency decision (WASM runtime vs native
binding), the Monaco tokenizer integration, and the CST-driven outline/folding
providers.

---

## Tests

`brain/tests/app/agent/toolkit/test_code_query_toolkit.py` (12 tests) covers exact
symbol and reference resolution, `context_at` slicing, and the grep fallback on an
unsupported extension. The assembler and tool-RAG suites stay green because the
repomix path is untouched.
