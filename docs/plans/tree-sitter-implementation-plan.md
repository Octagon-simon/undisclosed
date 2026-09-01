# Implementation Plan: Tree-sitter alongside Repomix for Project Understanding

**Status:** DRAFT — ready for Octagon's review
**Date:** 2026-09-01
**Companion doc:** `docs/reviews/project-context-tree-sitter.md` (the "why")
**Scope:** Turn the 3-part recommendation into an executable plan.

---

## Ground truth (verified in code)

- Current flow: `brain/app/agent/toolkit/project_context_toolkit.py` → shells `npx repomix --compress --stdout`, truncates to 60k chars, caches under `~/.eigent/project-context/` keyed on workdir-hash + git HEAD. Fail-soft when `npx` is missing.
- Wiring point: `brain/app/agent/factory/toolkit_assembler.py`
  - Config flag at line 79: `"project_context": {"enabled": True}`
  - Wiring (lines ~426–435): construct toolkit, then `assembly.add_tools(toolkit.get_tools(), Toolkit.toolkit_name())`.
- Toolkit base class: `brain/app/agent/toolkit/abstract_toolkit.py` (`AbstractToolkit.get_tools()` returns `list[FunctionTool]`).
- Tests live at `brain/tests/app/agent/toolkit/` (see `test_depth_limited_agent_toolkit.py` for the pattern).
- **tree-sitter is NOT currently a dependency anywhere** in the repo — backend or frontend. Earlier note about Monaco bundling a tokenizer was incorrect (those were unrelated UI "tree"-widget files). This is a **greenfield add** on both sides.

---

## Recommendation recap (the 3 parts)

1. **R0 — Keep repomix as the broad digest.** No change. Not a task.
2. **R1 — Backend `code_query` toolkit** (tree-sitter, precise symbol/reference/context queries). Do first.
3. **R2 — Frontend Theia/Monaco editor integration** (incremental highlighting, outline, folding via CST). Bigger, separate track.

Only **R1** and **R2** are work items. The plan below is sequenced R1 → R2.

---

# R1 — Backend `code_query` toolkit (do first)

> ✅ **STATUS: IMPLEMENTED** (single PR). All R1.1–R1.6 done; unit + assembler
> tests pass. `tree-sitter`, `tree-sitter-language-pack`, `tree-sitter-python`
> added to `brain/pyproject.toml` and installed into `brain/.venv`.
> `CodeQueryToolkit` lives at `brain/app/agent/toolkit/code_query_toolkit.py`,
> wired into `toolkit_assembler.py` behind the `code_query` config flag
> (enabled by default), and registered as a **core** toolkit in
> `tool_rag.py::_CORE_TOOLKIT_MARKERS` so its surgical lookups are always
> reachable (same treatment as `understand_project`). Tests in
> `brain/tests/app/agent/toolkit/test_code_query_toolkit.py` (12 pass) + the
> existing assembler/tool-RAG suites still green. Repomix path untouched.

**Goal:** Give the agent exact, structural answers to "where is `X` defined?", "who calls `bar()`?", "what's the enclosing function at line N?" instead of guessy grep/RAG — complementing, not replacing, `understand_project`.

### R1.1 — Dependency
- Add to `brain/pyproject.toml`:
  - `tree-sitter` (Python bindings)
  - `tree_sitter_language_pack` (bundles ~100 compiled grammars; avoids per-language pip packages)
- **Trade-off note for reviewers:** this adds a native wheel + build step (~tens of MB) to the backend image — unlike repomix's zero-setup `npx`. Confirm image size / build is acceptable before starting. If not, scope to a small set of grammars via individual `tree-sitter-<lang>` wheels.

### R1.2 — New toolkit module
Create `brain/app/agent/toolkit/code_query_toolkit.py`:

```python
class CodeQueryToolkit(AbstractToolkit):
    agent_name = Agents.single_agent

    def __init__(self, api_task_id, working_directory=None, agent_name=None)
    # lazy-load language pack so import fails-soft
```

Expose these tools (each a `FunctionTool` wrapping a method):

| Tool | Purpose |
|---|---|
| `find_symbol(name)` | Exact definition locations (file/line/range) from parsed CST — not regex hits in comments/strings. |
| `find_references(name)` | Real call/usage sites from the CST. |
| `callers_of(function_name)` | Enclosing functions that call a given function (call-graph via CST query). |
| `imports_of(path)` | Import/require statements of a file. |
| `context_at(path, line)` | The enclosing top-level definition (func/class) containing `line`, returned as parsed subtree text — ideal minimal slice for the LLM. |
| `file_symbols(path)` | Outline of a file (functions/classes/variables) for orientation within one file. |

Supported languages: map file extensions → grammars (e.g. `.py→python`, `.ts/.tsx→typescript`/`typescript`, `.js→javascript`, `.json→json`, `.go→go`, `.java→java`, `.rs→rust`). Query packs via `tree_sitter_language_pack`.

**Design rules (mirror the existing fail-soft philosophy):**
- If the language pack / a grammar isn't available, **fall back to grep** and note it, never throw to break a turn.
- No language grammar found for a file → fall back to grep.
- Cap returned context (e.g. `_MAX_CONTEXT_CHARS` ~8k) so a single answer can't blow the window.
- All methods are **read-only** — no governance gating needed (unlike `file_write`/`terminal` write paths).

### R1.3 — Wire into assembler
In `brain/app/agent/factory/toolkit_assembler.py`:
- Add config flag near line 79: `"code_query": {"enabled": True}`
- Add import near line 51.
- Add a wiring block beside the existing `project_context` block (~lines 426–435):

```python
if _enabled(config, "code_query"):
    code_query_toolkit = CodeQueryToolkit(
        api_task_id=options.project_id,
        working_directory=working_directory,
    )
    assembly.add_tools(
        code_query_toolkit.get_tools(),
        CodeQueryToolkit.toolkit_name(),
    )
```

### R1.4 — Register in the catalog (load_capability / tool RAG)
Check how `ProjectContextToolkit`'s tool name surfaces to the LLM's `load_capability` catalog and the per-turn tool-RAG selector (`ToolRAGSelector`). Register `CodeQueryToolkit` the same way so it can be pulled in on demand without always shipping its schemas. (Verify the exact registration path during implementation — the toolkit names feed both `capability_catalog()` and per-turn selection.)

> **Resolution (implemented):** The tool-RAG system (`app/agent/tool_rag.py`) is
> fully **dynamic** — `ToolRAGSelector` consumes whatever tools the assembler
> tags (the `_toolkit_name` set via `_tag_tools`), so no static catalog exists to
> update. The only static bit is `_CORE_TOOLKIT_MARKERS`, and we added
> `"code query"` there so `find_symbol`/`find_references`/etc. are always
> attached alongside `understand_project` (not gated behind RAG relevance).

### R1.5 — Tests
- `brain/tests/app/agent/toolkit/test_code_query_toolkit.py`
  - `find_symbol` returns exact definition for a fixture file (assert file + line, and that a comment mention is NOT returned).
  - `find_references` returns only real usages (not string literals).
  - `context_at` returns the enclosing function body for a mid-function line.
  - **fail-soft:** unsupported extension / missing grammar → returns grep fallback note, no raise.
- Run: `cd brain && pytest tests/app/agent/toolkit/test_code_query_toolkit.py`.

### R1.6 — Manual validation
Trigger the single-agent tool belt, call `find_symbol("ProjectContextToolkit")` and `find_references("understand_project")` against a checkout; confirm answers are exact and fast. Confirm `understand_project` still works unchanged (repomix untouched).

---

# R2 — Frontend Theia/Monaco tree-sitter integration (separate track)

**Goal:** Use tree-sitter for the *editor experience* — incremental, error-tolerant highlighting, semantic outline, folding/breadcrumbs — which repomix can never provide.

> ⚠️ Confirm first: is desktop-editor quality the driving requirement, or only the agent's internal context? If only agent-side, **skip R2** and stop at R1. This is the more expensive, long-leverage track.

### R2.1 — Decide dependency strategy
- Option A (recommended for an IDE): use a Theia/VS Code-style tree-sitter service. In a Theia app this means either
  - a tree-sitter **WASM runtime** (no native build; used by browser monaco via `@web-tree-sitter/wasm`), and
  - per-language grammar `.wasm` files (from `tree-sitter-grammars` / `wasm` distributions), or
  - a Node native binding on the backend for heavy lifting.
- Given the app is an Electron/Theia desktop product (`agent-ui`), evaluate which host (main process vs. webview) will run the parser.

### R2.2 — Wire Monaco tokenizer
- Confirm which editor frontend is active (`monaco-editor` confirmed in `agent-ui/node_modules/monaco-editor`).
- Integrate tree-sitter as a custom **Monarch / semantic token provider**, or a custom tokenizer, driven by the CST so it:
  - **re-parses incrementally** on edit (tree-sitter's core strength),
  - **keeps highlighting correct while typing**, even for incomplete code (error-tolerant).
- Keep an explicit **fallback** to Monaco's built-in tokenizer on any tree-sitter/runtime failure.

### R2.3 — Add editor features from the CST
- **Outline (document symbols):** functions/classes/variables side panel → implement a Monaco `DocumentSymbolProvider` sourced from the parsed tree.
- **Folding:** `FoldingRangeProvider` from CST node ranges (more reliable than indentation-based).
- **Breadcrumbs / symbol navigation:** derived from the same tree.
- **Bracket matching** stays correct via CST node extents.

### R2.4 — Reuse between frontend & backend
- Aim to use the **same grammar set** (language pack) on both sides. If the full `tree_sitter_language_pack` is accepted in R1, the frontend can align grammars to it; keep grammar/version selection centralized (a small config map) so syntax features match the backend's queries.

### R2.5 — Tests & validation
- Unit: parser produces a CST for a sample file; incremental edit re-parse is bounded and fast.
- Monaco provider integration tests: `foldingRanges` and `documentSymbols` match expected node ranges.
- Manual: open a large file, type mid-document, verify highlight/outline remain correct with no flicker/regression vs. the fallback tokenizer.

---

# Sequencing & ownership

| Step | Effort | Depends on | Owner |
|---|---|---|---|
| R1.1 dep + acceptance of native wheel | S | — | Review gate (Octagon) |
| R1.2 `CodeQueryToolkit` | M | R1.1 | Eigent |
| R1.3 assembler wiring | S | R1.2 | Eigent |
| R1.4 catalog/load_capability registration | S | R1.2 | Eigent |
| R1.5 tests | M | R1.2 | Eigent |
| R1.6 manual validation | S | R1.3–1.5 | Eigent + Octagon review |
| R2.1 dependency/runtime decision | M | decision: desktop quality? | Octagon |
| R2.2 Monaco tokenizer | L | R2.1 | Eigent |
| R2.3 outline/folding/breadcrumbs | M–L | R2.2 | Eigent |
| R2.4 grammar alignment w/ backend | S | R2.2, R1 | Eigent |
| R2.5 frontend tests & validation | M | R2.2–2.4 | Eigent + Octagon |

**Suggested cut:** land **R1 as a single PR** (prototype `code_query`, `find_symbol` + `context_at` minimum, grep fallback). Keep **R2** as a separately scoped track pending the "desktop quality?" decision.

---

## Open questions for review
1. Is the **native tree-sitter wheel** (backend image size + build step) acceptable for R1? If not, scope grammars down.
2. Is **desktop/editor quality** a real requirement (justifies R2), or do we stop at the agent-side toolkit (R1)?
3. Should `code_query` be gated behind the same env `enabled` flag pattern, or always-on once wired (it's read-only, so always-on is safe)?
4. Language priority for R1 grammars — proposal: python, typescript/tsx, javascript, json first.
