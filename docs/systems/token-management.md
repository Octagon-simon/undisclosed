# Token management

**Problem.** An agentic loop is brutally input-heavy. Function calling is
stateless, so every tool's schema is re-sent on every model call. With ~15
toolkits plus a connected MCP catalog that can be 60-100+ schemas, tens of
thousands of tokens go out on *every step of every turn*, at 0% cache. Add the
growing conversation, huge tool outputs, and image attachments, and a single task
can hit 50-60K input tokens per step.

We measured this directly. The `[USAGE]` log line (see below) showed "hii" sending
101 of 145 tool schemas, roughly 50K input tokens, and a task hitting 60K
input/step after one MCP toolkit dumped ~40K of Asana schemas.

**Solution.** A set of layered budgets and caps, all of which default to safe
values and degrade to "no savings" rather than "lost capability". None of them
require a model call on the hot path.

---

## 1. The token unit: a char proxy

Everything uses the same rule of thumb: **1 token ~= 4 chars**. It appears in:

- `brain/app/memory/context_builder.py` (`_chars_for`)
- `brain/app/memory/hybrid/config.py::token_estimate` and `assembler.py`
- the frontend chat store

It is deliberately rough: the goal is proportional budgets that are cheap to
compute, not exact accounting.

---

## 2. Durable-context section budgets

`ProjectContextBuilder.build` (`brain/app/memory/context_builder.py`) splits the
memory token budget across weighted sections, with hard caps on top:

```python
_HEADER_WEIGHT = 0.15       # space + project identity
_SUMMARY_WEIGHT = 0.25      # cumulative rolling summary
_RECENT_CONVO_WEIGHT = 0.50 # most recent conversation tail
_ARTIFACTS_WEIGHT = 0.07
_TODOS_WEIGHT = 0.03

_MAX_RECENT_CONVO_EVENTS = 24
_MAX_SUMMARY_CHARS = 4000
```

Each section is then fitted newest-first to its char budget, and a single
oversized item (one HTML report as an `final_result`) is **truncated** with a
marker instead of injected whole, so one pathological turn cannot blow the prompt.

Budget source: `UNDISCLOSED_MEMORY_TOKEN_BUDGET` (default 8000).

---

## 3. Compaction tiers (what we keep, what we gist)

`_render_single_agent` implements three tiers:

- **Tier 2, stable prefix vs volatile delta.** The space/project/facts/artifacts/
  todos block is byte-identical across requests for a project, so the provider
  prompt cache can collapse it. Only the per-turn parts (rolling summary, recent
  conversation, current instruction) go in the delta. This is why the cumulative
  summary lives in the delta: putting a per-turn-changing string in the stable
  prefix would invalidate the cache every single turn.
- **Tier 1, drop redundant facts.** A "Known facts" bullet whose text already
  appears verbatim in the visible conversation is skipped (that line *is* the
  pointer).
- **Tier 0, gist assistant turns.** Prior assistant turns are collapsed to their
  first sentence (`_ASSISTANT_GIST_MAX_CHARS = 240`) plus a `[see full result]`
  pointer, instead of resending the model's own verbose output. User turns stay
  verbatim, because they carry the intent.

---

## 4. Rolling-summary budgets

`brain/app/memory/rolling_summary.py` caps both the rendered document and every
field, so one giant turn cannot dominate:

```python
_USER_MAX_CHARS = 300
_DID_MAX_CHARS = 500
_ROLLING_MAX_CHARS = 2000
_MAX_FILES = 20
```

`char_budget()` (default 6000) and `keep_turns()` (default 8) drive
`compact_if_over_budget`, which folds the oldest turns into the `rolling`
narrative (bounded, newest-tail kept) while the newest turns stay at full detail.

---

## 5. Hybrid context budgeting

`brain/app/memory/hybrid/assembler.py` and `config.py` allocate the budget as
**fractions** so any total works, and shift them by query type (§25):

- Base: instructions 0.06, active_memory 0.10, working_memory 0.08, historical 0.26, exact 0.10, recent 0.40.
- Exact-recall query: more `exact` and `historical`, less `recent`.
- Continuation: more `recent` and `working_memory`, and **zero** `exact` and `historical` so stale episodes cannot leak in.
- Retrieval sizes are capped: semantic k=6, lexical k=8, exact k=4, rerank k=8.

Sections shrink or drop entirely when they have nothing to say, so the block never
carries empty scaffolding.

---

## 6. Tool-RAG: the biggest lever

**Module:** `brain/app/agent/tool_rag.py` (see also
[../features/tool-rag.md](../features/tool-rag.md)).

Function-calling re-sends every schema every step. Tool-RAG exposes, per turn,
only a small always-on core plus the tools that actually matter:

- **Core set** always exposed: `human`, `file`, `terminal`, `todo`, `memory`,
  `note`, `message`, `skill`, `project context`, `code query`, `search`.
- **LLM router**: a throwaway, memory-isolated `ChatAgent` picks which toolkits the
  task needs from a *compact* catalog (toolkit name + sample tool names, **not**
  schemas). The main agent then gets the full schemas of only those toolkits.
- **Embedding fallback** with a relevance threshold (`UNDISCLOSED_TOOL_RAG_MIN_SCORE`,
  default 0.10): a tool must clear the bar before it, and its toolkit, attach.
  Weak messages ("hii", ~0.06-0.09) expose core only.
- **Atomic toolkits**: when any tool of a toolkit is relevant, expose the whole
  toolkit so the agent never dead-ends on a fragment (e.g. `browser_visit_page`
  without `browser_click`).
- **Per-toolkit cap** (`UNDISCLOSED_TOOL_RAG_MAX_PER_TOOLKIT`, default 12): a
  30-tool MCP contributes its most relevant 12, not all 30.
- **`load_capability` meta-tool**: the agent can attach a toolkit mid-task for
  needs the opening message did not imply. Its tools are bound on the next step.

Kill switch: `UNDISCLOSED_TOOL_RAG=0` (keeps all tools). Any failure inside
Tool-RAG also keeps all tools.

---

## 7. Snapshot caps and dedup (workforce)

`brain/app/utils/agent_memory.py` bounds the in-process agent-memory snapshots
(which would otherwise blow the 200K in-process budget with 6+ workforce agents
plus accumulator duplication):

```python
UNDISCLOSED_SNAPSHOT_MESSAGE_CAP   = 4000   # per message content
UNDISCLOSED_SNAPSHOT_TOOL_ARG_CAP  = 2000   # per tool-call string field
UNDISCLOSED_SNAPSHOT_TASK_FIELD_CAP= 8000   # task_content / task_result
```

- `_shrink_tool_arguments` recursively caps long strings such as
  `write_file(content=...)` or base64 blobs.
- `record_workforce_memory_snapshot` dedups messages across the ~6 workforce
  agents (accumulators are near-clones of their workers), keeping only messages
  not already seen in an earlier scope.
- `build_memory_context` caps the *rendered* context too: 3 snapshots, 12 messages
  per snapshot, 1200 chars per message.

These apply only to the snapshot accumulator, never to what the live agent sees.

---

## 8. Tool-result truncation and step timeouts

`brain/app/agent/listen_chat_agent.py`:

- Non-string tool results are `repr`'d and truncated to `MAX_RESULT_LENGTH = 500`
  before being narrated.
- `AGENT_STEP_TIMEOUT_SECONDS` (default 600): a whole step, including a tool that
  blocks on human input, is bounded so a stuck browser call fails in minutes, not
  half an hour. (A non-positive value disables it.)
- `UNDISCLOSED_MAX_ITERATION` (default 0 = unbounded): an optional cap on
  tool-call rounds per turn. It defaults to unbounded on purpose, because a blunt
  low cap truncated legitimate long tasks; the real "runs forever" case is handled
  by the deferred-follow-up fix (see
  [../features/agent-runtime-hardening.md](../features/agent-runtime-hardening.md)).

---

## 9. Image attachments: never re-billed twice

A vision block is sent once (the turn the image is attached), but left in agent
memory it was re-encoded and re-billed on every later turn. `run_turn` now calls
`_collapse_memory_images()` at the start of each turn: prior memory records that
carry an image are rewritten to a text caption (a one-off vision *description* of
the image, or a generic marker on failure), so the image's content survives as
text without re-sending bytes. Vision blocks are also gated on
`model_supports_vision`, so a text-only model never receives a block it ignores.

---

## 10. Observability: measure before you optimize

`ListenChatAgent._on_request_usage` (`listen_chat_agent.py`) logs a per-request
line:

```
[USAGE] agent=... req#N input=... cached=...(..%) output=... total=... | step_total=...
```

It reads cached-input tokens across OpenAI/Anthropic/Gemini/DeepSeek usage shapes
(the default CAMEL flattening dropped them, which made `cached=0` a *false* zero
even when the provider was caching). It also emits `ActionRequestUsageData` over
SSE for the UI usage view. This is what made the tool-RAG wins measurable, so keep
it working.

---

## 11. Size-guard incidents (context for the guards)

Two raw exports in the repo root document real "too large" failures that led to
guards:

- `reasoning-too-large.md` and `payload-too-large.md`: oversized transcripts and
  payloads that stalled or bloated turns. The durable fixes were the step timeout,
  the tool-result truncation, the snapshot caps, and the deferred-follow-up queue
  (so a follow-up sent mid-turn runs as its own clean turn instead of being
  injected into a huge in-flight context).

---

## Summary of the levers

| Lever | Where | Default |
| --- | --- | --- |
| Char proxy (1 tok ~= 4 chars) | context_builder, hybrid config | always on |
| Section weights / hard caps | context_builder | 0.15/0.25/0.50/0.07/0.03, caps 24 events / 4000 chars |
| Stable prefix vs volatile delta | context_builder | always on |
| Gist assistant turns | context_builder | 240 chars |
| Rolling summary budget / keep | rolling_summary | 6000 chars / 8 turns |
| Hybrid section fractions | hybrid config/assembler | see §5 |
| Tool-RAG (router + threshold + cap) | tool_rag | on; 0.10; 12/toolkit |
| Snapshot caps / dedup | agent_memory | 4000 / 2000 / 8000 |
| Tool-result truncation | listen_chat_agent | 500 |
| Step timeout | listen_chat_agent | 600s |
| Iteration cap | single_agent factory | 0 (unbounded) |
| Memory token budget | service | 8000 |
| Usage logging | listen_chat_agent | always on |
