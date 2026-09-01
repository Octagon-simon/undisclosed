# Review: Repomix → Tree-sitter for Project Understanding

**Date:** 2026-09-01
**Author:** Eigent review for Octagon
**Scope:** Whether to replace the current repomix-based `understand_project` flow with tree-sitter.

---

## TL;DR

**Don't replace repomix — that would be a downgrade.** But there's a **strong, clean win** in *adding* a tree-sitter-backed tool alongside it for **targeted, syntax-aware queries** (symbol lookups, call graphs, definition jumps). The two tools solve different halves of the same problem, and neither subsumes the other.

Recommended path:
1. **Keep** repomix for the broad, whole-repo digest (it's already working well and cached).
2. **Add** a tree-sitter-based `code_query`/`symbol_search` toolkit for precise per-file/per-symbol questions.
3. Optionally wire tree-sitter into the **frontend (Theia/Monaco)** for the *editor* experience, which is where tree-sitter's real leverage lives for an IDE.

---

## What the current flow actually is

I read the real implementation at `brain/app/agent/toolkit/project_context_toolkit.py`.

```python
cmd = ["npx", "--yes", "repomix@latest", "--compress", "--stdout", "--quiet"]
```

Facts about the current flow:
- It shells out to `npx repomix --compress --stdout`, then truncates to a **60,000-char cap**.
- The digest is **cached per project** under `~/.eigent/project-context/`, keyed on a hash of the working dir + the git HEAD (`rev-parse HEAD`). It **only regenerates when git HEAD changes** or `refresh=True`.
- `focus=<glob>` is supported to re-scan a subset.
- It is **fail-soft** — if `npx`/repomix isn't available, it returns a polite note and the agent falls back to normal grep/file search.
- It's exposed to the agent as a single `understand_project` tool (from the Single-Agent toolkit assembly).

So "the repomix flow" = **one cached, whole-repo, compressed text blob** handed to the LLM. Good for broad orientation; weak for precision.

---

## 30-second primer on tree-sitter

Tree-sitter is not a "context dumper" — it's a **parser generator + incremental parsing library** that produces a **concrete syntax tree (CST)** for real code in ~100 languages. Its unique properties:

- **Incremental**: re-parses only the changed region on each edit (ms-scale). This is why it underpins syntax highlighting in VS Code, Neovim, etc.
- **Error-tolerant**: yields a usable tree even on partial/broken code (it never throws).
- **S-expression / queryable**: you can run declarative queries (tree-sitter "queries") to extract symbols, functions, call sites, imports, etc. structurally.
- **Structured, not text**: you get node types (`function_definition`, `call_expression`), positions, and parent/child relations — not greppable text.

Note: the tree-sitter reference in this repo is **only transitive** — it lives deep inside `agent-ui/node_modules/monaco-editor`, which bundles a tree-sitter-based tokenizer for the editor. It is **not** a project dependency and is **not** currently reachable from the `brain/` backend.

---

## Head-to-head

| Axis | repomix (current) | tree-sitter |
|---|---|---|
| Whole-repo orientation | ✅ Strong — one compressed blob | ❌ Weak — it's a per-file parser, not a summarizer |
| Precise symbol search | ❌ Weak — text/RAG, guessy | ✅ Strong — structural, exact |
| Call-graph / definition jump | ❌ Not natively | ✅ Strong (query CST) |
| Incremental on edit | ❌ Full re-run on HEAD change | ✅ Native, ms-scale |
| Error tolerance / partial files | ❌ repomix skips unparseable | ✅ Strong |
| Natural-language context for LLM | ✅ Native (it is an LLM-oriented digest) | ❌ You must roll your own summarizer |
| Works out of the box | ✅ Yes (`npx repomix`) | ⚠️ Needs one grammar dependency per language |
| Cached & keyed to git HEAD | ✅ Already done | ▸ Would need your own caching layer |

**The sharp distinction:** repomix produces *semantic context the LLM can read*. Tree-sitter produces *syntax structure a program can query*. They are orthogonal.

---

## Recommendation (3 parts)

### 1. Keep repomix as the broad digest (no change)

Attempting to "do what repomix does" with tree-sitter means building:
- a per-language CST walker,
- a summarizer to convert raw structure back into natural language,
- a caching layer keyed to git HEAD,
- a truncation/ranking strategy,

…to reproduce something that `npx repomix --compress` already does in one command today. That's **re-implementing the product** with strictly more engineering for the same or worse result. The whole-repo digest problem is a **language-model problem**, and tree-sitter is not a language model.

### 2. Add a tree-sitter `code_query` toolkit to `brain/` (medium-value, more effort)

The gap in the current flow is **precision**. Today the agent's only fast path to "where is `Foo` defined / who calls `bar()`?" is grep/RAG over text. A small toolkit backed by a Python tree-sitter binding (e.g. `tree-sitter` + `tree_sitter_language_pack` for ~100 grammars) would give the agent:

- `find_symbol(name)` — exact definition locations (not regex-hits on comments/strings).
- `find_references(name)` / `callers_of(func)` — real call sites from the CST.
- `imports_of(path)`, `class_hierarchy(type)` — structural answers.
- `context_at(path, line)` — the enclosing function/block parsed as a tree, ideal for slicing minimal context into the model.

This slots into the exact architecture you already have: a new class in `app/agent/toolkit/` wired into `toolkit_assembler.py` the same way `ProjectContextToolkit` is today. It's **additive** — `understand_project` stays for orientation, `code_query` answers the surgical follow-ups.

Cost reality check: unlike repomix (zero-setup via `npx`), tree-sitter needs a **Python native dependency** (`tree_sitter_language_pack` bundles compiled grammars — adds ~tens of MB and a build step to the backend image). That's a real trade to weigh against the precision gain.

### 3. Wire tree-sitter into Theia/Monaco for the *editor* experience (biggest bang)

This is the part repomix will *never* do. The repo already pulls in Monaco's tree-sitter tokenizer in `agent-ui`. For an IDE-grade product the compelling wins are **front-end**:

- **Incremental, error-tolerant syntax highlighting** vs. one-shot tokenization.
- **Semantic ranges / outline** (functions/classes side panel) from the CST.
- **Editor features** (folding, bracket matching, breadcrumbs) driven by the live tree, staying correct as the user types.

If the "handle project contexts" goal extends to *the editor experience* (not just the agent's internal digest), **tree-sitter belongs in the frontend**, and the agent can optionally reuse the same grammar set.

---

## Suggested next steps

1. **Ship repomix + tree-sitter `find_symbol`/`context_at`** as the thin backend addition — highest value-to-effort for the *agent's* context handling. Keep repomix as-is.
2. Prototype in one PR: a `code_query` toolkit, a single new tool (`tree_sitter_language_pack`), fall through to grep on error (same fail-soft philosophy repomix already uses).
3. Treat **Theia/Monaco editor runtime** as the separated frontend track for tree-sitter — measure whether desktop-editor quality (not the agent digest) is the driving requirement; if so, budget there.
4. **Do not** invest in a from-scratch "tree-sitter digest" to replace repomix. It's a re-build of a solved problem.

---

## Bottom line

- ✅ **Add tree-sitter** as a *complement* for precise structural queries and for the frontend editor.
- ❌ **Do not replace repomix** with it — the whole-repo digest stays text/LLM-based, cached, and fail-soft.

It's very much "something we can add to improve the way we handle project contexts" — but as a **companion**, not a **replacement**.
