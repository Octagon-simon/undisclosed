# Hybrid Conversational Memory: Implementation Notes

Implements `hybrid_memory.md` on top of the existing local-first memory layer
(`brain/app/memory/`). The whole feature is additive and gated behind
`UNDISCLOSED_HYBRID_MEMORY`; the proven rolling-summary path keeps serving until
the hybrid retrieval is evaluated.

## Where it lives

    brain/app/memory/hybrid/
      config.py      env-driven knobs (window, thresholds, weights, budgets)
      schema.py      Episode, StructuredMemory, MemoryOp, WorkingMemory, retrieval types
      text.py        tokenization, entity extraction, BM25 (pure)
      canonical.py   application-controlled memory-key identity (§13)
      storage.py     HybridStore: episodes.json / memories.json / working_memory.json
      lexical.py     BM25 + exact retrieval over raw messages (§17)
      vector.py      chromadb episode index (fail-soft) (§16)
      extractor.py   boundary-aware episodes + memory-op proposals (§6-14, §29)
      router.py      deterministic routing + escalation (§18, §22)
      ranking.py     hybrid score + rerank (§21)
      assembler.py   tagged, budgeted context (§24-27)
      engine.py      parallel retrieval + async run-end pipeline (§19, §28)

Raw messages are unchanged: they remain `ConversationEvent` rows in the existing
`conversation.jsonl`, and nothing here rewrites them (§3, golden rules 1-2).

## Spec section map

    3   raw messages          existing ConversationEvent transcript (untouched)
    4-5 recent window + thresholds   config + extractor.plan_eviction
    6   boundary-aware eviction      extractor.find_boundary / plan_eviction
    7   episodes                     schema.Episode + extractor.build_episodes
    8   no recursive master summary  episodes are independent; rolling_summary untouched
    9   episode summary content      extractor.build_episode (extractive)
    10-11 structured + versioned     storage.apply_ops (version + supersession)
    12  explicit mutation ops        schema.MemoryOp + storage validation
    13  stable memory identity       canonical.identity / normalize_key
    14  working memory               WorkingMemory + extractor.update_working_memory
    15-17 hybrid retrieval           engine.retrieve (semantic + lexical + exact + memory)
    18  retrieval router             router.route (no LLM on the critical path)
    19  parallel retrieval           engine.retrieve (ThreadPoolExecutor)
    20  no interrupt-and-append      retrieve-before-generation only
    21  hybrid ranking               ranking.score_item / rerank
    22  escalation                   router.route levels 1-5 + router.escalate
    23  source linking               every RetrievedItem/Episode keeps source_message_ids
    24  context assembly             assembler.assemble (tagged sections)
    25  context budgeting            assembler._fractions_for (per query type)
    26  grounded evidence            <exact_historical_evidence> + "prefer verbatim" note
    27  context rules                <memory_rules> block
    28  async extraction pipeline    engine.process_run_end / schedule_process_run_end
    29  memory worthiness            extractor.is_worthy + user-role-only mining
    33  episode boundaries           natural boundary, then max_turns cap
    34-39 retrieval examples         covered by router + evidence_found classification
    43  observability                retrieval_log.jsonl + RetrievalResult.diagnostics
    45  runtime flow                 service.build_durable_context_for_task_lock + on_run_end

## Runtime integration

- **Before generation** (§19, §45): `MemoryService.build_durable_context_for_task_lock`
  calls `hybrid_engine.build_context` when the flag is on. That routes, runs the
  lanes concurrently, reranks, and assembles the tagged block. Failure or an
  empty result falls back to the existing durable-bundle path.
- **After the response** (§28): `MemoryService.on_run_end` calls
  `hybrid_engine.schedule_process_run_end`, which (by default) runs on a daemon
  thread so extraction + embedding stay off the response path. It plans
  boundary-aware eviction, builds and embeds episodes, applies validated memory
  ops, and updates working memory. Idempotent via the coverage watermark.
- **On demand**: the agent gets a `recall_history` tool (episodes + exact
  evidence + active/superseded memory), complementing the existing
  `recall_conversation` / `recall_turns`.

## Enabling

    UNDISCLOSED_HYBRID_MEMORY=true

All tuning knobs are documented in `.env.sample`. Defaults are conservative:

- recent window 6,000 tokens; soft 0.8 / hard 1.0 thresholds,
- semantic k=6, lexical k=8, exact k=4, rerank k=8,
- ranking weights favour semantic + lexical + recency,
- extraction + background pipeline on (only reached when the master flag is on).

## Deliberately not shipped

- **LLM-backed episode/memory summarization.** The pipeline is fully
  deterministic and free (same reasoning as the rolling-summary work: `on_run_end`
  is synchronous, so there is no event loop to await a model). The extractor is
  structured so an LLM merge can slot in behind the same `Episode`/`MemoryOp`
  shapes once an async chokepoint exists.
- **Raw-message vector indexing.** Episodes are indexed; raw messages are served
  by lexical/exact retrieval (§16 allows indexing messages later if evaluation
  shows value).
- **PostgreSQL tables (§31-32).** The local-first filesystem store is the
  project's stance; the JSON sidecars mirror the suggested tables 1:1 and can be
  migrated without changing the engine API.

## Tests

    cd brain && .venv/bin/python -m pytest tests/app/memory/ -q

`tests/app/memory/conftest.py` disables the chromadb index so tests never touch
`~/.undisclosed/memory`. Coverage: store round-trip + versioned ops, canonical
keys, BM25 + exact retrieval, eviction/boundaries/episodes, memory-op
extraction + worthiness, working memory, routing + escalation, ranking,
assembly/budgeting/grounding, the end-to-end run-end pipeline, the service
wrapper, and the `recall_history` tool.
