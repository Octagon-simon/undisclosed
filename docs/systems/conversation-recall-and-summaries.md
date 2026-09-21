# Conversation recall and cross-conversation summaries

**Problem.** The agent forgets what it just did.

`run_turn` resets the reused model's message history every turn (deliberately: it
fixed a verbatim-repeat loop), so the model does not carry its own prior turns.
The only durable context fed back was a thin tail that **gists every assistant
turn to its first sentence**. A plan or diagnosis lives in the assistant body, so
it was dropped and the next turn re-derived it. Worse, the agent's
`recall_conversation` tool was a raw keyword scan that returned fragments, not the
plan.

Observed symptom that drove the work: turn 1 produced a full diagnosis and plan;
turn 2 ("go ahead and implement") had no memory of it, called `recall_conversation`,
got fragments, and re-researched.

**Solution.** Three pieces:

1. A **cumulative rolling summary** written after every turn and injected at the
   start of the next.
2. Upgraded **recall tools** that consult that summary first, then the raw
   transcript.
3. A **hybrid recall** tool (`recall_history`) that searches by meaning when the
   keyword scan is not enough.

---

## 1. The cumulative rolling summary

**Module:** `brain/app/memory/rolling_summary.py`
**Plan/design:** [rolling-conversation-summary-plan.md](../../rolling-conversation-summary-plan.md)

The core invariant:

```
new_summary = merge(previous_cumulative_summary, this_turn_digest)
```

Turn N's stored summary is always a summary of turns 1..N together, never a bag of
independent per-turn summaries. That is what stops detail from decaying.

**Storage** (under the existing `LocalMemoryStore` tree, keyed by `project_id`,
which equals the chat/turn id in this app):

```
~/.undisclosed/memory/users/<user>/spaces/<space>/projects/<project>/summary.json   # source of truth
                                                                    /summary.md      # rendered view
```

The `.json` holds structured `TurnDigest` entries plus a `rolling` narrative and
lets us compact, re-render, and backfill with no model call. The `.md` is the
small, budgeted text that gets injected.

**Deterministic, free.** Tier A builds each digest from data already present at
turn end: the user prompt from `task_lock.conversation_history`, the
`final_result`, the run status, and the files touched (parsed from the run's tool
events). Zero model calls on the default path. Overflow compaction folds the
oldest turns into `rolling` instead of calling a model.

**Write chokepoint.** `MemoryService.on_run_end` calls `_write_rolling_summary`
(`brain/app/memory/service.py`). Every end path (single agent, workforce, skip,
stop, failure) funnels through it, so one hook covers them all. It is idempotent
per `run_id` via `task_lock._memory_finalized_runs`.

**Injection.** `ProjectContextBuilder` (`brain/app/memory/context_builder.py`)
renders the summary in the **volatile delta**, never the stable prefix. The stable
prefix (space/project/facts/artifacts/todos) is byte-identical across requests so
the provider prompt cache can collapse it; a per-turn-changing summary there would
invalidate that cache every turn. There is also a fallback path
(`read_rolling_summary_for_task_lock`) so continuity survives even when the
durable bundle is unavailable.

**Config** (`UNDISCLOSED_ROLLING_SUMMARY*`, see `.env.sample`):

- `UNDISCLOSED_ROLLING_SUMMARY` (default on)
- `UNDISCLOSED_ROLLING_SUMMARY_CHAR_BUDGET` (default 6000): render size above which compaction folds older turns
- `UNDISCLOSED_ROLLING_SUMMARY_KEEP_TURNS` (default 8): recent turns kept at full digest detail
- `UNDISCLOSED_ROLLING_SUMMARY_BACKFILL` (default on): build an initial summary for conversations that predate the feature

---

## 2. The recall tools

**Module:** `brain/app/agent/toolkit/memory_toolkit.py`

| Tool | What it does |
| --- | --- |
| `recall_conversation(query)` | **This** conversation. Summary-first for a broad query; otherwise a raw per-turn keyword scan over the turn store. |
| `recall_turns(k)` | The last K structured turn digests (ordered), for reconstructing a multi-step plan. |
| `recall_history(query)` | Hybrid retrieval (see below) when you need to recall by meaning or an exact detail. |
| `recall_facts(query)` | User/space-scoped semantic facts (see [memory-system.md](memory-system.md)). |
| `remember_fact(fact)` | Save a durable fact, proactively. |

`recall_conversation` distinguishes **broad** queries ("the plan", "what we
decided", "continue", "where were we", "status") from narrow lookups. For a broad
query the cumulative summary *is* the answer, so it returns the summary directly
instead of a keyword scan that would only surface fragments. For a narrow lookup
it scans the raw turn store (`~/.undisclosed/turns/<api_task_id>/turn_*.json`,
scores by term frequency, returns the top snippets), and falls back to the summary
before giving up.

---

## 3. Cross-conversation / cross-session recall

Two mechanisms reach *beyond* the current conversation:

- **Semantic facts are user-scoped.** `semantic_store.recall()` filters by user,
  not by project, so a personal fact (name, preference, decision) surfaces across
  every conversation. Relevance is handled by embedding similarity. See
  [memory-system.md](memory-system.md).
- **`recall_history` and the hybrid engine** (`brain/app/memory/hybrid/engine.py`)
  search episodes, exact raw messages, and structured memory in parallel. When the
  retrieval plan is *not* a continuation, `engine.retrieve` widens to global
  memory plus the user's other projects, and each hit carries its `scope` and
  `origin_project_id` so the model knows where it came from.

**Caveat (honest).** Cross-project widening brings in *memory* from other
projects, not their episodes or raw transcripts. An exact-history question about a
different project cannot yet escalate to that project's transcript.

---

## Tests

`brain/tests/app/memory/test_rolling_summary.py` pins the cumulative invariant
(turn 1, then 2, then 3; the stored doc references all of them together),
compaction preserving folded turns, atomic/idempotent append, and corrupt-file
recovery. `brain/tests/app/agent/toolkit/test_memory_toolkit.py` covers the
summary-first recall behavior. The section 36 regression scenarios live in
`test_memory_regression_scenarios.py`.
