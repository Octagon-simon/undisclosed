# Memory system

**Problem.** A coding agent that cannot remember is a stateless chatbot. It needs
to remember at three different time scales:

- what happened **this conversation** (the plan, the decisions),
- what is true about the **user and their projects** across all conversations,
- and how to retrieve either **by meaning**, not just by keyword.

**Solution.** A local-first memory stack under `brain/app/memory/`, layered from a
durable filesystem store up to a hybrid retrieval engine. Almost everything is
fail-soft: a memory glitch logs and returns empty, it never breaks a chat turn.

---

## The layers

```
brain/app/memory/
  events.py            dataclasses: ConversationEvent, MemoryFact, ProjectMemory, RunMemory, SpaceMemory, ...
  paths.py             on-disk layout + canonical_user_id
  local_store.py       LocalMemoryStore: the durable filesystem store (JSON/JSONL)
  rolling_summary.py   cumulative per-conversation summary (see conversation-recall doc)
  context_builder.py   assembles a budgeted context bundle for the prompt
  service.py           MemoryService: run/project/space lifecycle hooks
  semantic_store.py    vector facts (chromadb, local MiniLM)
  hybrid/              the hybrid conversational memory engine
```

### 1. Durable store (`local_store.py`, `paths.py`)

Everything lives under a per-user tree, owned by a canonical user key:

```
~/.undisclosed/memory/
  users/{canonical_user_id}/spaces/{space_id}/projects/{project_id}/
    projects.json / summary.json / summary.md / conversation.jsonl / runs/...
```

`conversation.jsonl` is the raw audit trail of `ConversationEvent` rows (the
golden rule: nothing rewrites raw messages). Everything else is a derived view.
Writes are atomic and guarded by a per-path lock.

### 2. Lifecycle hooks (`service.py`)

`MemoryService` is the thin facade callers use. A chat turn triggers:

- `on_run_start` -> ensure space/project records, write the run header, append the user message.
- `on_run_end` -> append the assistant result, set run status, write the rolling summary, and (if hybrid is on) schedule the run-end pipeline.

Every hook is wrapped so a memory write failure cannot break chat.

### 3. Semantic facts (`semantic_store.py`)

Distilled facts and run outcomes are embedded with chromadb's on-device MiniLM
(`onnxruntime`), stored in a `PersistentClient` under
`~/.undisclosed/memory/semantic` (collection `undisclosed_facts`). **Fully local,
nothing leaves the machine.**

- `remember(user, space, project, text, source=...)` upserts with a stable id per
  `(project, text)` so identical facts dedupe on rewrite.
- `recall(user, space, project, query, k=5)` filters by **user** (not project), so
  personal facts surface across all of a user's conversations.
- `count()` / `clear()` / `prune()` back the Memory settings screen.

Recall is spliced into the prompt automatically as a `<remembered_facts>` block
(`service._build_semantic_recall_section`). The agent can also save and recall
explicitly via `remember_fact` / `recall_facts` (the Memory Toolkit).

**Pollution guard.** Only *substantial* outcomes are stored:
`_remember_run_outcome` skips short greeting chatter ("Hi! How can I help?") and
caps stored text at ~800 chars, because storing greetings made the agent
re-answer earlier turns.

### 4. Hybrid conversational memory (`hybrid/`)

An additive, env-gated engine (`UNDISCLOSED_HYBRID_MEMORY`, default off) that
implements the `hybrid_memory.md` spec. Read
[plans/hybrid-memory-implementation.md](../plans/hybrid-memory-implementation.md)
for the full module-to-spec-section map. Highlights:

- **Episodes**: boundary-aware eviction turns older messages into independent
  episode summaries (no recursive master summary).
- **Structured memory with identity**: `MemoryOp` proposals pass through a single
  validation gate (`HybridStore.apply_ops`) that stamps scope, versions, and
  supersession, keyed by a canonicalized memory identity (`canonical.py`).
- **Hybrid retrieval**: semantic + lexical (BM25) + exact + memory lanes run in
  parallel, then a deterministic router chooses the plan and a ranker blends the
  signals. No LLM on the critical retrieval path.
- **Budgeted, tagged context**: `assembler.py` renders `<memory_rules>`,
  `<historical_evidence>`, `<exact_historical_evidence>`, `<active_memory>`,
  `<working_memory>`, `<recent_conversation>` with per-query-type budget shifts.
- **Durable jobs**: post-run extraction runs off the response path; with
  `UNDISCLOSED_HYBRID_DURABLE_JOBS` (default on) it is a recoverable job in
  `<user>/memory_jobs.json`, so a lost thread or a restart does not lose the
  memory (see `brain/app/memory/hybrid/jobs.py`).

---

## Scope, projects, and provenance

These are what make "who does this fact belong to" and "which project is this
about" answerable.

- **Scope** (`scope.py`, `schema.py`): memories carry `scope_type`/`scope_id`.
  `GlobalMemoryStore` gives global memory a user-root home, and `infer_scope` /
  `resolve_op_scope` apply the promotion rules that decide when a project-scoped
  fact becomes user-global.
- **Projects** (`project.py`): `ProjectStore` keeps a user-level registry
  (`<user>/projects.json`) plus conversation to project links
  (`<user>/conversations.json`). `discover()` unions the registry with an on-disk
  walk that reads each project's existing `project.json`, so trees that predate
  this layer resolve with no migration.
- **Project resolution** (`resolver.py`): strongest-signal-first, explicit id
  (1.0) > durable conversation link (0.9) > name/description match > single active
  project. Low confidence returns no project so retrieval broadens instead of
  guessing. A semantic-match layer blends project-description embeddings in when
  lexical matching fails (`project_semantic.py`).
- **Provenance** (`vector.py`, `apply_ops`): every Chroma document carries a
  durable id and provenance metadata (user/project/conversation/scope/type/status/
  importance/turn range/sourceMessageIds). A memory op that cites an unknown
  source id is dropped (`TestProvenanceGate`).

---

## Configuration

All knobs are in `.env.sample`. The ones you are most likely to touch:

- Master switch: `UNDISCLOSED_HYBRID_MEMORY` (off by default; the proven rolling
  summary path serves until hybrid retrieval is evaluated)
- Window/thresholds: `UNDISCLOSED_HYBRID_RECENT_TOKENS`, `..._SOFT_THRESHOLD`, `..._HARD_THRESHOLD`
- Retrieval sizes: `UNDISCLOSED_HYBRID_{SEMANTIC,LEXICAL,EXACT,RERANK}_K`
- Jobs: `UNDISCLOSED_HYBRID_DURABLE_JOBS`, `UNDISCLOSED_HYBRID_JOB_RECOVERY`
- Semantic project matching: `UNDISCLOSED_HYBRID_PROJECT_SEMANTIC*`
- Prompt budget: `UNDISCLOSED_MEMORY_TOKEN_BUDGET` (default 8000)

---

## What is deliberately not shipped

- **LLM-backed episode/memory summarization.** The pipeline is deterministic and
  free because `on_run_end` is synchronous (no event loop to await a model). The
  data shapes are structured so an async LLM merge can slot in later.
- **Raw-message vector indexing.** Episodes are indexed; raw messages are served
  by lexical/exact retrieval.
- **Postgres tables.** The filesystem store is the project's stance; the JSON
  sidecars mirror the suggested schema and can migrate without changing the
  engine API.

---

## Tests

```
cd brain && .venv/bin/python -m pytest tests/app/memory -q
```

The suite (261+ tests) covers store round-trips, versioned ops, canonical keys,
BM25/exact retrieval, eviction and episodes, memory-op extraction, working memory,
routing/escalation, ranking, assembly/grounding, the end-to-end run-end pipeline,
project resolution, durable jobs, and provenance. `conftest.py` disables the
chromadb index so tests never touch the real `~/.undisclosed/memory`. The opt-in
`test_hybrid_vector_live.py` (`UNDISCLOSED_LIVE_CHROMA=1`) runs against a real
`chromadb.PersistentClient` and verifies index -> restart -> query durability plus
the legacy-collection migration.
