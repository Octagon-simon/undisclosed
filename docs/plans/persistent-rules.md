# Persistent Rules: implementation plan

Status: decisions locked 2026-10-23. Phases 0-6 implemented and verified on
2026-10-23. See "Implementation notes" at the end for the small deviations.
Source spec: `persistent-rules-memory.md` (repo root).
Scope: the brain (`brain/app/memory/**`, `brain/app/agent/**`) and the activity
trace (`agent-ui/src/lib/activityClassifier.ts`, `UserQueryGroup.tsx`).

---

## 0. TL;DR

The spec is right about the shape of the fix, and this repo is closer to it than
it looks. `StructuredMemory` already has scope, status, version, provenance, and a
deterministic mutation gate (`HybridStore.apply_ops`). What is missing is five
small things:

1. **A detector that runs when the message arrives**, not at run end.
2. **An always-on read of active constraints**, independent of the query. Today a
   memory only reaches the prompt if it shares a keyword with the question.
3. **Uniqueness for constraints.** Every generic "never X" rule is stored under
   the key `constraint`, so the second rule silently supersedes the first.
4. **A prompt section that says "these are standing constraints"**, instead of
   dropping them into the same `<active_memory>` list as preferences.
5. **A recall probe**, so the agent occasionally checks its own memory instead of
   assuming the always-on block is complete.

Plus the two things asked for directly: the trace labels, and a real destination
for what the agent decides to save on its own.

Estimated diff: ~650 lines of Python (two new modules, one loader, one detector,
small edits in 6 files), ~40 lines of TypeScript, ~420 lines of tests.

---

## 1. What the code actually does today

Verified by reading, not assumed:

- Memory types are `fact | preference | decision | constraint | goal`
  (`brain/app/memory/hybrid/schema.py:42`). Scope is
  `global | project | conversation`; ops are `UPSERT | SUPERSEDE | DELETE | MERGE`
  (`schema.py:293-320`).
- Writes happen **at run end**, not at message receipt:
  `finalize_task_lock_run_memory` -> `service.on_run_end`
  (`brain/app/memory/service.py:398-456`), which calls `engine.on_run_end` and
  runs the deterministic extractor plus, in `write` mode, the LLM pass
  (`engine.py:1016-1054`).
- The deterministic extractor **does** detect prohibitions: `_CONSTRAINT_RES`
  matches "never", "do not", "must not", "avoid", "shouldn't"
  (`extractor.py:417-427`) and emits `type="constraint"` ops
  (`extractor.py:507-514`).
- Retrieval requires a **term or entity overlap** with the query:
  `_lookup_memories` returns nothing when no shared term exists
  (`engine.py:285-307`). The lane is also gated on `lane_plan.use_memory`
  (`engine.py:437`).
- Context is injected on every turn through
  `build_durable_context_for_task_lock` (`service.py:107-216`), called from
  `single_agent_service.py:236` and `chat_service.py:443`.
- The agent's own save path is `remember_fact`, which writes **only** to the
  chroma collection (`agent/toolkit/memory_toolkit.py:112` ->
  `semantic_store.remember`). It creates no `StructuredMemory`, so it has no
  type, no scope, no lifecycle, and is not part of always-on loading.
- The hybrid layer's master switch and the LLM extraction pass now default to
  on / `write` in code (`config.py`), so no `.env` override is needed to run
  them (Phase 0).

---

## 2. Why the license rule gets lost (seven distinct causes)

Each one is independently enough to lose the rule. The spec is correct that these
must be checked separately.

**C1. No rule-shaped detection at message time.** Detection happens in
`on_run_end`, after the agent has finished the turn. A crash before that callback,
or a run that never reaches it, loses the rule.

**C2. Constraints share one identity, so they overwrite each other.**
`_constraint_key` (`extractor.py:536-537`) returns `"constraint"` whenever
`_key_from_text` finds no known noun, and that vocabulary is ~32 words. Two
different prohibitions therefore collide, and the second supersedes the first.

**C3. Retrieval is query-coupled.** A rule is loaded only if it shares a term or
entity with the current query (`engine.py:285-307`), and only if the lane router
decided `use_memory` (`engine.py:437`). Ask something unrelated and the rule is
not in the prompt at all.

**C4. No notion of "hard".** Nothing distinguishes a standing constraint from a
preference, so nothing can say "this is non-negotiable".

**C5. Constraints are rendered as ordinary memory.** `_render_memories`
(`assembler.py:85`) prints one flat list under `<active_memory>`. Without a
dedicated section, the model reads a rule as background trivia.

**C6. The agent's save destination is weaker than the extractor's.** When the
agent calls `remember_fact` on its own, the text goes to chroma only. It never
becomes a scoped, versioned, always-on record.

**C7. Nothing enforces a rule at the action boundary.** Every rule is a prompt
hope. For licensing this matters most, and it is deliberately **out of scope**
(decision 4).

---

## 3. Design

### 3.1 Reuse `StructuredMemory`, do not add a second registry

A parallel `rules.json` would duplicate scope, status, version, provenance and
supersede semantics, then drift. So:

**A rule is a `StructuredMemory` with `type="constraint"`, plus the fields in
3.2.** "Persistent rule" is a lens over structured memory, not a new store.
Chroma stays a discovery index and is never on the rule read path.

### 3.2 Schema additions (backward compatible)

In `brain/app/memory/hybrid/schema.py`, add to `StructuredMemory`:

```python
severity: str = "soft"          # hard | soft
enforcement: str = "prompt"     # prompt | tool_guard | both
category: str = ""              # licensing | security | coding | workflow | product | privacy | other
original_text: str = ""         # verbatim user wording, never fabricated
last_confirmed_at: str = ""     # bumped when the user repeats the rule
guard: str = ""                 # reserved; no guard ships in this pass
```

`from_dict` uses `_clean` (field-filtered), so existing `memories.json` records
load unchanged and default to `soft` / `prompt`.

Add `SEVERITIES` and `ENFORCEMENT_MODES` next to `MEMORY_TYPES`, and reject
unknown values in `apply_ops` the same way unknown types are rejected today
(`storage.py:262-271`).

`enforcement` and `guard` ship as data only. Nothing reads them for behavior in
this pass; they exist so a later guard does not require another migration.

### 3.3 Key uniqueness for constraints (fixes C2)

Change `_constraint_key` to always produce a value-derived key:

```
slug = first 3-4 significant words of the value, lowercased, underscore-joined
key  = f"rule_{slug}" if slug else f"rule_{sha1(normalized_value)[:8]}"
```

Properties:

- Two different rules can never share an identity, so nothing supersedes
  accidentally.
- The same rule stated twice produces the same key and value, so `_apply_upsert`
  merges idempotently and we bump `last_confirmed_at` instead of duplicating.
- Human-readable keys in `memories.json`.

Migration: existing `type="constraint"` records with `key="constraint"` get
re-keyed from their value on the next write. Before re-keying, print what would
change and how many records collide; never drop a record silently.

### 3.4 Detection at message receipt (fixes C1)

New module `brain/app/memory/hybrid/rule_detect.py`:

```python
@dataclass
class RuleCandidate:
    text: str            # normalized, actionable
    original: str        # verbatim
    scope: str           # global | project | conversation
    category: str
    severity: str        # hard | soft
    key: str
    confidence: float

def detect(text: str) -> list[RuleCandidate]: ...
```

Detection signals:

- **Explicit persistence markers:** "always", "never", "from now on", "every
  time", "hard rule", "don't forget", "remember this", "under no circumstances",
  "must not", "do not".
- **Repetition signal:** the same rule seen before (same key) promotes to hard
  and bumps `last_confirmed_at`. This is the "you've told me five times" case.
- **One-time exclusion:** "for this email", "just this once", "this time", "in
  this draft", "for now" -> `conversation` scope, never global, never hard.
- Reuse `extractor._CONSTRAINT_RES` rather than writing a second dialect.

Pure and synchronous: one regex pass over one message. No model, no latency.

**Call path (decision 2: same turn):**

```
incoming user message
  -> rule_detect.detect()
  -> RuleWriter.apply()                      # durable write through apply_ops
  -> build_durable_context_for_task_lock()   # loads it as always-on
  -> agent runs
```

A small `record_turn_rules(task_lock, user_prompt)` helper next to
`build_durable_context_for_task_lock`, called at the top of
`_build_single_agent_context` (`single_agent_service.py:229`) and the equivalent
spot in `chat_service.py:443`.

If the write raises, log the rule text and continue without the rule. Never
report success before the file write returns.

**No hardcoded rules.** The detector reads the user's message; the loader reads
memory records. No rule text (licensing or otherwise) lives in code, in a seed
file, or in a migration. This is decision 5 and it is deliberately absolute:
rules come from what the user stated and what memory holds.

### 3.5 Always-on loading (fixes C3, C4, C5)

New `brain/app/memory/hybrid/rules.py`:

```python
def read_active_rules(
    base_store, *, user_key, space_id, project_id, conversation_id
) -> list[StructuredMemory]
```

- **Same read path as today's injected memory.** It opens the project
  `memories.json` and the `GlobalMemoryStore` user-level file, the same two
  records `build_durable_context_for_task_lock` already consults. No new file, no
  second representation.
- Filter: `status == "active"` and `type == "constraint"`.
- `conversation`-scoped records are included when
  `scope_id == conversation_id`.
- Precedence for the same key: conversation > project > global. Different keys
  are all kept, ordered hard-first.
- **No caching (decision 1).** Two small JSON reads per turn are microseconds.
  A cache is exactly how a stale or empty rule set loses a rule, and it is not
  worth the risk. If profiling ever shows this matters, revisit with a stat-based
  invalidation, not a TTL.
- No Chroma call, no query, no lane gating. A Chroma outage cannot remove a rule;
  a `LEVEL_RECENT` continuation routing decision cannot remove one either.

Rendering, in `assembler.py` (prepended to `assemble`, and also emitted by the
non-hybrid fallback path so behaviour is identical with the flag off):

```xml
<persistent_rules>
Standing constraints from this user. Treat every hard rule as a requirement on
every action in this turn, regardless of what the current request asks for. If
two rules conflict, stop and ask instead of choosing.
- [hard][<category>][<scope>] <rule text> (stated <date>)
</persistent_rules>
```

The block is emitted **only when at least one rule exists**. There is no
placeholder rule and no fallback text: an empty store means an empty block.

Budget: a fixed ~15% slice of the memory budget, not subject to query-type
fractions, because a continuation turn needs rules as much as a fresh one.
Truncate individual rules at ~400 chars; never drop a hard rule to fit; drop the
oldest soft rules first.

### 3.5.1 Recall probe (decision 5)

The always-on block is authoritative, but the agent should occasionally verify
that its recall is not empty or stale instead of assuming. Two triggers:

1. **Empty block:** no active rules were loaded. The prompt gets a short
   `<recall_check>` asking the agent to call
   `recall_facts("standing rules constraints preferences")` once before acting,
   and to say nothing if it returns nothing.
2. **Periodic:** every 10th user turn in a task (derived from the task lock's
   event count, no new state), even when rules did load, ask for the same check
   and a one-line internal confirmation. No user-facing narration.

Wording is explicit about failure: "If the tool returns nothing, do not claim to
remember it." That kills the class of answer where the agent asserts a rule from
vibes.

### 3.6 Agent-initiated saves (fixes C6)

Change `MemoryToolkit.remember_fact` to accept optional structure, keeping the
one-argument call valid:

```python
remember_fact(fact: str, kind: str = "fact", scope: str = "auto",
              key: str = "", category: str = "") -> str
```

Routing:

- `kind in {"rule", "constraint"}` -> structured `StructuredMemory` with
  `type="constraint"`, `severity="hard"`, `original_text=fact`, written through
  `apply_ops`, **and** indexed in chroma for discovery. It becomes always-on.
- everything else -> chroma as today, plus a project-scoped `StructuredMemory`
  when `key` is given.

Return string changes from `"Remembered: {fact}"` to `"Saved to memory."`.

Prompt changes (`brain/app/agent/prompt.py:961-970`): replace the vague
"proactively" bullet with concrete triggers:

- The user states a constraint, prohibition, or approval requirement.
- The user corrects you about how you should work ("don't do that again",
  "always X").
- The user states a preference or a stack choice that affects future work.
- You make a decision the user should not have to re-explain next session.
- You learn a stable environment fact (paths, versions, accounts, tooling).

Plus: save silently in one call, never narrate "let me remember that", never ask
permission to save a fact the user just stated.

### 3.7 Activity trace labels (decision 3)

`agent-ui/src/lib/activityClassifier.ts:663-678`, memory branch:

| call | running | finished |
|---|---|---|
| `remember_fact` | `Writing to memory` | `Written to memory` |
| `recall_*` | `Recalling from memory` | `Recalled from memory` |

Mechanics: set `verb` to the full phrase and `object` to `''`; the renderer
already handles an empty object (`ActivityTraceCard.tsx:332-335`). Remove
`Remembered: 'Remembering'` and `Recalled: 'Recalling'` from `PAST_TO_GERUND`
(`activityClassifier.ts:499-500`), and change `CATEGORY_NOUNS.memory` from
`['memory','memories']` to `['memory write','memory writes']`.

Also rename the injected-block chip title `'Remembered Facts'` -> `'Memory'`
(`UserQueryGroup.tsx:81`).

### 3.8 Enforcement: dropped

Decision 4. No tool guards, no shell script at the action boundary, no
`UNDISCLOSED_RULE_GUARDS` flag. `enforcement="tool_guard"` and `guard` remain
unused fields in the schema so adding a guard later is additive, not a migration.

### 3.9 Env knobs: removed

Decision: stop relying on `UNDISCLOSED_HYBRID_MEMORY` and
`UNDISCLOSED_HYBRID_LLM_EXTRACTION` overrides. Their code defaults move to the
values that are proven to work (`enabled()` -> `True`, LLM extraction ->
`write`), then the two lines leave `.env`. Behaviour on this machine is
unchanged; the flags remain readable for debugging and for other installs that
want to turn the layer down.

`UNDISCLOSED_HYBRID_EXTRACTION` and `UNDISCLOSED_HYBRID_BACKGROUND` already
default to `True`, so those `.env` lines are redundant as well and are removed
with no code change.

Flagged: this changes the default for fresh installs from "memory off" to "memory
on". That is the point of "leave them on default since it works", but it is a
product-wide default, not a local change.

---

## 4. Phases

**Phase 0: env defaults** (small, removes a moving part)
- `config.enabled()` -> `True`, `llm_extraction_mode()` default -> `write`,
  docstrings updated.
- `.env`: drop the four hybrid lines.
- Update the two tests that assert the old default.

**Phase 1: schema + key fix**
- `schema.py`: new fields, `SEVERITIES`, `ENFORCEMENT_MODES`, validation.
- `extractor.py`: `_constraint_key` -> value-derived key.
- `storage.py`: reject invalid `severity` / `enforcement`; stamp `original_text`.
- One-off re-key of colliding records + a test proving two constraints coexist.

**Phase 2: always-on loader + prompt section**
- `rules.py`: `read_active_rules`, no cache.
- `assembler.py`: `<persistent_rules>` section, fixed budget slice.
- `service.py`: call the loader in `build_durable_context_for_task_lock` before
  the hybrid/legacy branch, so both paths get it; thread rules into
  `build_context` so the hybrid path does not double-render.

**Phase 3: turn-time detection**
- `rule_detect.py` + `record_turn_rules` + two call sites.
- Idempotent via key; repeat bumps `last_confirmed_at` and promotes to hard.
- Honest failure: no success claim without a completed write.

**Phase 4: agent-initiated structured saves**
- `memory_toolkit.remember_fact(kind, scope, key, category)`.
- `prompt.py` bullets.

**Phase 5: recall probe**
- `rules.should_probe(...)` (empty block, or every 10th turn).
- `<recall_check>` rendering in the assembler.
- Prompt wording that forbids claiming a rule the tool did not return.

**Phase 6: surface + trace**
- `activityClassifier.ts` labels, remove old verbs, group noun.
- `UserQueryGroup.tsx` chip title.

**Phase 7: verify**
- Backend suite, `run_checks`, `review_diff`, `coverage_gap_plan`.
- Manual: state a rule in chat A, restart the brain, open chat B, ask something
  unrelated, confirm `<persistent_rules>` contains it and the model obeys.
- Manual: `remember_fact` a rule, confirm it appears as `Written to memory` and
  is loaded on the next turn without a keyword match.

---

## 5. Tests

Backend, `brain/tests/app/memory/`:

- `test_rule_detect.py`: positive/negative cases; "for this email only" stays
  conversation-scoped; "always remember the license rule" -> hard, licensing,
  project; repeat detection is idempotent (one record, confirmed twice); a rule
  with no keyword overlap to any later query still loads.
- `test_rules.py`: `read_active_rules` with Chroma mocked to raise; precedence
  conversation > project > global; revoked/superseded excluded; another user's
  project not visible; **no rule text exists anywhere in the source** (assert the
  rendered block is empty when the store is empty).
- `test_hybrid_storage.py` additions: two distinct constraints coexist; identical
  restatement merges and bumps `last_confirmed_at`; invalid `severity` dropped.
- `test_service_lifecycle.py` additions: `record_turn_rules` writes before
  context build; a failing write leaves no rule and no success claim.
- Probe: empty store -> `<recall_check>` present; non-empty store on turn 3 -> no
  probe; turn 10 -> probe.
- Prompt-level test: build the real context string and assert
  `<persistent_rules>` and the rule text appear (assert on the payload, not the
  store).

Frontend: `agent-ui/src/lib/activityClassifier.test.ts` asserting
`Writing to memory` / `Written to memory` / `Recalling from memory` /
`Recalled from memory`.

Regression: `scripts/check-license-headers.sh` passes; new files get the Simon
banner, edited upstream files get the Portions line.

---

## 6. Decisions (locked 2026-10-23)

1. **Where hard rules load from** -> same store as today's injected memory, read
   on every turn, **no caching**. A cache that can go empty or stale is the exact
   failure being fixed.
2. **Same turn** -> yes. Detect, write, then build context.
3. **Trace wording** -> `Writing to memory` / `Written to memory` for writes,
   `Recalling from memory` / `Recalled from memory` for recalls. Both states,
   no "Remembered" anywhere.
4. **Tool guards** -> skipped. No enforcement phase.
5. **Backfill** -> none. No hardcoded or seeded rules; the system learns from the
   conversation. Plus an occasional recall probe so the agent checks whether it
   actually recalls.

Additional locked points:

- No rule text is hardcoded. Rules come from the user's message and from memory.
  This also keeps other installs from inheriting one person's licensing policy.
- Env knobs for the hybrid layer are removed in favour of working defaults.

---

## 7. Implementation notes (2026-10-23)

Shipped as planned, with five deliberate deviations:

1. **Tests live in one module.** `brain/tests/app/memory/test_hybrid_rules.py`
   covers detection, identity, loading, rendering, the probe, and both context
   paths. The plan's separate `test_rule_detect.py` / `test_rules.py` split was
   not worth three files for the same fixtures.
2. **Restatements match on wording, not only key.** `apply_ops` looks for an
   active constraint with the same normalized value before writing a new key, so
   the existing `license_rule_reminder` record merges instead of gaining a
   duplicate. The record keeps its original key.
3. **A quality bar for legacy rows.** `read_active_rules` always loads hard rules
   and all global rules. Soft project/conversation constraints written by the old
   extractor must be at least 20 chars and carry three content words. Without
   this, fragments like "not describe it" would become standing instructions.
   This is the only filter the plan did not specify.
4. **The re-key migration is a script, not automatic.**
   `brain/scripts/rekey_hybrid_constraints.py` is dry-run by default and reports
   the 26 legacy `key="constraint"` records on this machine; `--apply` rewrites
   the key only.
5. **The UI test is `agent-ui/src/lib/activityClassifier.test.ts`.** It also
   asserts that a narration `message_title` cannot override the memory label.

### 7a. Follow-up fix (2026-10-24): `remember_fact` reported a false failure

`remember_fact(kind="rule")` returned "Saved to the memory index, but the
always-on rule store was unavailable" on live turns. The store was up; the guard
was wrong. `_write_structured` required `user_key`, `space_id`, and
`api_task_id` for every scope, but a `global` record lives at the user root and
never uses the space. A chat request may omit `space_id`
(`Chat.space_id: str | None = None`; `resolveSpaceIdForProject` returns
undefined for legacy/unknown spaces), so every rule save degraded to index-only
while `record_turn_rules` (which reads `run_context.space_id`, resolved as
`space_id or project_id`) kept working.

Fixed:

- `MemoryToolkit` resolves the space the same way `RunContext` does, and both
  construction sites pass `options.space_id or options.project_id`.
- Per-scope requirements: `global` needs the user key only; project and
  conversation also need the space.
- The failure message names the actual reason (`no user key for this run`,
  `store write raised ...`, `store rejected the record`) instead of claiming the
  store was down.
- Verification matches the record by `canonical.identity(type, key)` or by
  `canonical.normalize_wording(value)`, so a restatement merging into a legacy
  key is not reported as a failed write.
- `read_active_rules` and `record_turn_rules` fall back to `project_id` when the
  space is missing, so a project rule is not silently dropped.

Regression tests: `brain/tests/app/agent/toolkit/test_memory_toolkit.py`.

### 7b. Follow-up fix (2026-10-24): legacy severity and the re-key run

Two items stayed open after `28b50df`.

**Legacy rows rendered `[soft]`.** `severity` was added after the first
constraint rows were written, so an old rule stored `soft` whether or not the
user made it non-negotiable, and a restatement was the only way to change it.
`read_active_rules()` now labels those rows from the only evidence left, their
wording, before the sort, budget, and rendering see them:

- a legacy row is one without the `original_text` / `last_confirmed_at` stamp
  that every writer since has set (a later round-trip may have copied the
  `soft` default in, so the stored value alone cannot identify it);
- legacy rows that read as a policy (`must`, `never`, `always`, `do not`,
  `don't`, `no ... unless`, `before any ...`) become `hard`;
- legacy rows that read as description ("macOS only ...", "--init-truth refuses
  to ...", "CIEDE2000 must be computed ..." stays hard because it says "must")
  stay `soft`;
- conversation-scoped legacy rows stay `soft`;
- an explicit `soft` written after the field existed is never promoted.

The quality bar runs first, on the recorded severity, so a fragment cannot
promote itself past it (`must not` alone is still dropped). With the real store
this moves the four global rules (tool-call visibility, typecheck-before-done,
no Slack writes, the license reminder) to `[hard]` and leaves the descriptive
project rows soft.

**The migration had not been run.** `rekey_hybrid_constraints.py --apply`
re-keyed all 26 active `key="constraint"` rows on this machine, 0 collisions. A
second dry run reports 0. Superseded rows keep the old key, since history is not
rewritten. The script now copies every file it touches into
`<root>/.rekey-backup-<stamp>/` before rewriting and goes through the store's
atomic writer, so a bulk edit of a user's memory tree is recoverable.

Regression tests: `brain/tests/app/memory/test_hybrid_rules.py`
(`TestLegacySeverity`) and `brain/tests/app/memory/test_rekey_hybrid_constraints.py`.

---

## 8. Non-goals

- No new vector collection. Chroma stays an index; structured memory stays the
  record.
- No rewrite of retrieval routing. Rules bypass the router by design.
- No automatic promotion of ordinary instructions to global rules.
- No LLM call on the turn path. Detection is regex plus deterministic scope.
- No tool guards, no enforcement.
- No seeded rules.
