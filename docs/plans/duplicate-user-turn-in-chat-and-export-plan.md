# Fix plan — duplicated user turn in chat and in the Markdown export

**Status:** diagnosis complete, design not implemented (awaiting your go-ahead).
**Trigger:** the exported conversation `there-is-a-company-that-i-am-working-for-and-part-of-their-g.md`
shows the same user message twice in a row (`## You` at lines 290 and 294).
**Related:** `docs/changes/2026-10-12-chat-stream-change-ledger.md` §2, §5.3, §9.2.

---

## 1. What you saw, exactly

The open export file ends with:

```
## You
i told you something about file changes and header attachments. … fix the file changes you misplaced their copyright headers

## You
i told you something about file changes and header attachments. … fix the file changes you misplaced their copyright headers
```

The **durable** record of that turn is clean. There is exactly one copy on disk:

- `~/.undisclosed/turns/1791984554717-5349/turn_1792007754113-6870.json`
  - `userMessage.content` = the message (one copy)
  - `otherMessages` = the single agent reply ("Rule saved. …")
- No other turn file in that chat contains the text (checked all 18).

So the copy you are seeing is **client-side only**. The turn store (the source of
truth) has it once; the chat store that feeds the export has it twice. This rules
out "the message was really sent twice" and points at **placement**, not transport.

---

## 2. Root cause

A single logical user turn can transiently live in **two tasks at once**, and the
conversation renders — and the export prints — **one section per task**. The same
turn then shows up twice.

The mechanism is documented in code, not guessed:

- `agent-ui/src/lib/dedupeUserTurns.ts` (header comment):
  > "When a follow-up is migrated out of the task it was optimistically added to
  > and into the fresh task created by the `confirmed` event, a late notice /
  > acknowledgement / the previous turn's `end` (or a re-emitted `confirmed` from
  > a re-attached stream) can leave a copy behind in BOTH tasks. Because the
  > conversation renders — and the export prints — one section per task, the same
  > turn then shows up twice."
- The migration lives in `agent-ui/src/store/chatStore.ts` in the `confirmed`
  handler (~lines 2630–2760). There is an idempotency guard (~2649–2675) and the
  source copy is supposed to be removed after the turn is moved, but the removal
  is not atomic with respect to *late* events (`notice` / acknowledgement / the
  previous turn's `end`) or a **re-emitted `confirmed` from a re-attached stream**.
  Those can land after the migration and re-place the copy.

**Why it shows up now:** the ledger already nails this — `4f9d8ee` (Oct 10) added
a **second stream per session** (resume/attach) plus a re-attach-on-follow-up
watchdog. More stream events re-emit `confirmed`/`wait_confirm`, which is exactly
the path that can double-place a turn. `4bef3db` had a text-based guard for this,
and §9.2 records that the guard's *hiding* half was reverted (a good call: it
could hide a legitimate repeat).

---

## 3. Why the current code does not catch it

Three readers walk the same data; only one still has a guard, and it is unused:

| Reader | De-dupes? |
|---|---|
| `ProjectChatContainer.tsx` (render, lines 127–149) | Only **across chat stores** (`seenTaskIds`). Does **not** collapse a turn duplicated across two **tasks**. |
| `exportChat.ts` (`exportActiveConversationToMarkdown`) | **Nothing.** Pushes every message of every task of every store into one flat list. |
| `collectDuplicateUserTurnIds` (`dedupeUserTurns.ts`) | The exact collapse needed — but **referenced only by its own test**. Neither render nor export calls it (confirmed: no non-test caller in `agent-ui/src`). |

So both the panel and the export are exposed; the export is just the one you
looked at. (If the panel looked fine at the time, it is because the second task
had no agent turn yet and read as an empty section — the export does not skip
those.)

---

## 4. Fix options

### Option A — Export-level only (smallest, safe, immediate)

Make `exportActiveConversationToMarkdown()` mirror how the UI builds sections
before it prints:

1. Group `collected` back into `{ taskId, messages }` sections in the same order
   the UI renders them (reuse the `seenTaskIds` rule from
   `ProjectChatContainer` so a task surfacing through two stores is counted once).
2. Run `collectDuplicateUserTurnIds(sections)` and drop the ids it returns
   (only the **second+** consecutive copy of the same user text with no agent turn
   between — a genuine repeat always has the agent's answer separating it).
3. Print the surviving messages.

- **Pros:** fixes the artifact you saw; no render change; reuses the tested helper.
- **Cons:** the duplicate still exists in memory and can still be shown by the
  panel in other states; it is a display-layer patch, not a cure.

### Option B — Re-wire the collapse into render + export

Same as A but also call `collectDuplicateUserTurnIds` inside `ProjectSection`
(restoring what `4bef3db` did, minus the bug).

- **Pros:** panel and export agree.
- **Cons:** this is the exact "hide a real message" trade the ledger flags. A
  legitimate repeat with no agent turn between (rare, e.g. a double-tapped send)
  would be hidden. I would not ship B without also doing C.

### Option C — Root fix: server-reconciled dedupe (recommended end state)

Stop the second copy from ever being created. In the `confirmed`/`wait_confirm`
handler, reconcile against the **persisted turns** for the chat (the
`~/.undisclosed/turns/<chatId>/` records, already reachable — see
`useSelectedProjectTurn` / `projectCache`) before placing or migrating a copy:
collapse only when the **turn id** and the **server turn record** agree, instead
of keying on text alone.

- **Pros:** correct at the source; both render and export become clean with no
  hiding; removes the whole class of "late event re-places the turn" bugs.
- **Cons:** touches the hottest path in `chatStore`; needs care (and a test) so it
  never drops a real turn.

---

## 5. Recommendation

Ship **A now** (it is the artifact you actually saw and it is low risk), then do
**C** as the real fix in the next pass; keep **B** out. Concretely:

1. A: `agent-ui/src/lib/exportChat.ts` — build task-ordered sections (mirroring
   `seenTaskIds`) and filter with `collectDuplicateUserTurnIds`.
2. Add a regression test beside `dedupeUserTurns.test.ts` that feeds an export
   fixture with the same turn in two tasks and asserts one block in the Markdown.
3. ~~C (next): reconcile in the `confirmed` handler against persisted turns.~~
   **Superseded — see §9.** The durable record is *frontend-authored* and, for a
   queued follow-up, is written **inside** the very `confirmed` handler that would
   reconcile; so C would read a record that does not exist yet. Do **D** instead.

---

## 6. Verification once implemented

- Unit: a fixture with the same user turn in two tasks → export yields **one**
  `## You` block; a genuine repeat with an agent reply between → **two** blocks.
- Manual: re-export this exact conversation; the tail should show the message once.
- Typecheck: `tsc` on `agent-ui`; run the export/dedupe tests.

## 7. Rollback

- A/B: revert the `exportChat.ts` (and, for B, `ProjectSection.tsx`) hunks — read-
  only change, no state touched.
- C: revert the `chatStore.ts` hunk; ledger §5.3 already lists the fallback
  (`git revert 4bef3db` territory — do not do that without re-checking the
  original duplicate-tprompt bug).

---

## 8. Research brief (handoff)

**Verdict:** the sections above are enough to *reproduce and locate* the bug,
but not by themselves enough to *research option C*. They name the fix but omit
the three things a researcher needs to reason about event ordering: the event
contract, a minimal repro trigger, and the durable-record shape. This section
adds exactly those. Every file:line anchor above was re-checked on 2026-10-14
and still holds.

### 8.1 The event contract (what can re-place a turn)

From `agent-ui/src/types/constants.ts` (`AgentStep`, lines 19-57), the steps
that touch user-turn placement are:

- `confirmed` (`'confirmed'`) — creates/adopts the follow-up task; the migration
  lives in this handler.
- `wait_confirm` (`'wait_confirm'`) — deferred-steer confirm.
- `notice` / `notice_card`, `acknowledge` — late notices that can land *after*
  the migration and re-place a copy.
- `end` — the previous turn's `end`.
- plus a **re-emitted `confirmed` from a re-attached stream** (the resume/attach
  stream added in `4f9d8ee`).

### 8.2 The four code touch-points for C

1. `agent-ui/src/store/chatStore.ts` ~2605-2740 — the `CONFIRMED` handler; the
   migration and its guard at ~2642-2679 (keyed on `previousChatStore.nextTaskId`).
2. `agent-ui/src/store/projectStore.ts` ~968-985 — `appendInitChatStore` is
   already idempotent *by task id*, but only when `customTaskId` (= the armed
   `nextTaskId`) is present; a re-emitted confirm with a null pointer falls
   through and mints a second task (see the comment at 968-972).
3. `agent-ui/src/components/ChatBox/index.tsx` ~1112-1237 — where a genuine
   follow-up arms `nextTaskId` *before* it POSTs. That pointer's presence/absence
   is the only signal the guard currently uses.
4. `agent-ui/src/lib/dedupeUserTurns.ts` — the collapse helper
   (`collectDuplicateUserTurnIds`), still test-only.

### 8.3 Minimal repro (the trigger to research)

Send a follow-up **while the current turn is still streaming** (so `nextTaskId`
gets armed), and force a stream re-attach mid-turn (the re-attach watchdog /
resume path). The re-emitted `confirmed` can then arrive when `nextTaskId` has
already been consumed, so late events (`notice` / ack / `end`) re-place the
copy in the source task. The export `there-is-a-company-…g.md` is the recorded
instance.

### 8.4 The durable record C must reconcile against

`~/.undisclosed/turns/<chatId>/turn_<queryId>.json`, JSON with:

- `chatId` (str)
- `queryId` (str) — equals the filename suffix; this is the server-side turn
  identity.
- `userMessage` (object) — `{ id, content, createdAt, attaches, fileList, agent_name }`
- `otherMessages` (array) — the turn's agent messages.
- `sessionMode`, `tokens`, `lastRequestTokens`

So C's phrase "the turn id and the server turn record agree" resolves concretely
to: **client user-message `id` ↔ durable `userMessage.id` / `queryId`**.
(Verified by reading the exact file cited in §1.)

### 8.5 Open questions for the researcher (my uncertainty about C)

1. **Task → turn mapping.** Every client task must map to exactly one durable
   `queryId`. Confirm `useSelectedProjectTurn` / `projectCache`
   (`agent-ui/src/hooks/useSelectedProjectTurn.ts`) exposes that link for
   *optimistic / replayed* tasks, not only completed ones.
2. **Which late event actually re-places.** Capture a live trace of a repro and
   confirm it is the re-emitted `confirmed` versus a `notice` / `end`. The fix
   differs by caller.
3. **Durable-write idempotency.** Verify the durable store never holds the turn
   under two chatIds (which would make reconcile-by-record also see two). §1
   shows it does not for this instance; confirm it generally.
   **Answered 2026-10-14 — see §9.2:** there is **no** delete route; `removeMessage`
   only mutates memory, so a stale user-only record *can* linger under the
   pre-migration chatId. Reconcile-by-record is therefore not trustworthy, and in
   any case the client already holds the id it would match on.
4. **Cost / placement.** C sits on the hottest path (every confirm). Decide
   whether the reconcile runs per-confirm or only on a detected re-emit.

---

## 9. Addendum — durable-write timing, and Option D (2026-10-14)

This closes open question 1's sibling ("when is the durable record written?") and
replaces C. Every anchor below was re-read on 2026-10-14.

### 9.1 The durable record is frontend-authored, and for a queued follow-up it is written *inside* the `confirmed` handler

The Brain exposes exactly **one** turn-write route:
`POST /api/v1/chat/{chat_id}/turns/{query_id}/messages`
(`brain/app/controller/chat_history_controller.py:109`), an upsert by
`(chatId, queryId)` (`_load_turn` L92-101, `_save_turn` L104-106, body L120-151).
`_save_turn` has a single caller (`post_message`), so **the Brain never writes a
turn by itself** — no turn is created at "turn end" on the server.

The writer is the renderer. `enqueueTurnPost` (`agent-ui/src/lib/turns.ts:97`)
posts through a **debounced** (50 ms — `scheduleFlushSoon` L87-95) retry queue
(`flushOnce` L61-85, backoff to 8 s). It is invoked from two `chatStore` persist
hooks:

- `addMessages` — the `role === 'user'` branch (`chatStore.ts:5374-5397`) and the
  `role === 'agent'` branch (`5400-5445`);
- `updateMessage` — re-persist of a content-bearing agent message (`1566-1647`).

So the record is **incremental, not turn-end**: the user row lands when
`addMessages('user')` fires; assistant rows append as they stream; the final
`tokens`/`fileList` update lands at `END`. The turn file *looking* complete at
rest (user + `otherMessages`, §8.4) is just the accumulated result, not evidence
of when it is first written.

**The timing hole is real, and in the repro it is deterministic.** When a
follow-up is sent *while the current turn is streaming*, the task is busy, so
`ChatBox.handleSend` does **not** add the user message — it adds a display-only
QueuedBox pill (`agent-ui/src/components/ChatBox/index.tsx`, the
`else { projectStore.addQueuedMessage(...) }` branch). The user message for that
turn is added later, **inside the `confirmed` handler itself**:

```ts
// chatStore.ts ~2817
newChatStore.getState().addMessages(newTaskId, {
  id: carriedUserId, role: 'user', content: userMessageContent, …
});
```

That `addMessages` is what enqueues the durable user row (debounced ≥50 ms). So at
the moment the handler would run C's reconcile, **the durable turn does not exist
yet** — C reads nothing and cannot collapse. For the idle follow-up it is a race
(durable POST enqueued after the improve POST; confirmed usually arrives later)
rather than a guaranteed miss, but still not a guarantee.

**And the read is unnecessary.** The durable file is keyed by
`queryId` = `userMessage.id`, which the client *already holds*: `nextUserId`
(minted in `handleSend`, `ChatBox/index.tsx`) → `carriedUserId`
(`chatStore.ts:2788-2796`). C's phrase "the turn id and the server turn record
agree" therefore carries **zero new information** over the in-memory id. The
reconcile collapses to "have I already placed a user turn with this id?", a
pure-memory question.

### 9.2 A stale record can exist under a second chatId

There is **no** `DELETE` on turns (grep: none in `chat_history_controller.py`) and
`removeMessage` (`chatStore.ts:5476-5493`) mutates memory only. So when the
migration's destination is a *different* `chatStore` than the optimistic add
(`appendInitChatStore` can mint one when no primary exists —
`projectStore.ts:888-935`), the source user-only record is left on disk under the
old chatId. Reconcile-by-record would then see the turn **twice** and could pick
the wrong side. (In the recorded instance `createChatStore` reused the active
chatId, `projectStore.ts:895-908`, so only one file existed — which is why §1 saw
one.)

### 9.3 Option D — in-memory placement guard (now recommended)

Smaller than C, on the hot path but **without any disk read**, and independent of
persistence timing:

1. **Track placed user-turn ids in memory.** Keep a `Set<string>` of user-turn
   ids (`nextUserId`/`carriedUserId`) already placed for the chat. The
   `CONFIRMED` (`chatStore.ts:2605-2820`) and `WAIT_CONFIRM` (`3270-3330`) guards
   consult it before creating or migrating: if the resolved id is already placed
   anywhere, treat the event as a re-emit and return. This replaces the current
   text-keyed, `nextTaskId`-presence guard (which is why a re-emitted confirm with
   a **null** `nextTaskId` slips through and mints a second task —
   `projectStore.ts:968-985`).
2. **Make migration + source-removal one atomic store update.** Today the source
   copy is removed (`chatStore.ts:2802-2816 removeMessage`) and the destination
   copy added (`2817 addMessages`) as two separate `set()` calls; a late
   `notice`/ack/`end` (or a re-emitted confirm) interleaving between them can
   re-place the copy. Fold "remove-from-source + add-to-destination" into a single
   `set()`. Late events then have nothing to re-place.
3. Reuse the ids already minted (`nextTaskId`, `nextUserId`); no new identity, no
   server round-trip.

**Cons / honesty:** it is still client-only state, so it does not survive a
reload mid-duplicate — but the durable store is single-copy anyway (§1, §9.2), so
a reload rehydrates clean. It needs the same care as C never to drop a *real*
turn; the `Set` must be seeded only on an actual placement, not on every confirm.

### 9.4 Revised recommendation

- **Drop C as designed** — it depends on a record that is written *after* the
  decision point in the exact repro, and reads an id the client already has.
- **Do D** as the root fix (in-memory id guard + atomic migration).
- **Keep A** only for already-persisted exports/history that D cannot retro-fix;
  never B.
- C becomes unnecessary; if durability across reload is ever wanted, the guard can
  optionally be seeded from the durable turn list on hydrate, but that is a
  cold-path concern, not the hot-path fix.

---

## 10. Implemented — Option D (id-keyed guard + atomic migration)

Landed. Everything below is code that exists now, not a proposal.

- **New:** `agent-ui/src/lib/userTurnPlacement.ts`
  - `PlacedUserTurnRegistry` (in-memory `Set` of placed turn ids) + the shared
    `placedUserTurns` instance.
  - `isReemittedUserTurn(...)` — the guard. Keyed on the turn **id**: if the id
    resolves, it is a pure "have I placed this id?" check with **no text
    comparison**. Only when the id cannot resolve (the turn already migrated,
    so `nextUserId` is gone and the trailing message is the agent's reply) does
    it fall back to finding a user message in the current task whose **id is
    already placed** AND whose content matches. Requiring a placed id means the
    fallback can only ever suppress a copy of a turn we already know about — it
    can never hide a genuine new turn.
  - `resolveSourceUserTurnId(...)` — extracts the existing by-id-then-trailing
    source resolution so it is unit-testable.
- **`chatStore.ts`:**
  - The `confirmed` migration resolves `sourceTurnId`, `userMessageContent`, and
    `attachesForNewMessage` **before** `appendInitChatStore`, then consults
    `isReemittedUserTurn` **before** creating any task. A re-emit returns early.
    This replaces the old text-keyed, `nextTaskId`-presence guard (which both
    could hide a legitimate same-text repeat and, when `nextTaskId` was null,
    let a re-emit mint a second task).
  - The turn is marked placed (`placedUserTurns.markPlaced`) only on an actual
    placement, so the guard can never swallow a real turn.
  - **Atomic migration (guard 2):** when the source and destination tasks live
    in the same chat store (the common case — `appendInitChatStore` reuses the
    primary store), the source removal and the destination append now happen in
    **one `set()`** via a new `removeSource` option on `addMessages`. When a
    fresh chat store was minted (different stores) it falls back to remove-then-
    add, the previous behaviour.
  - **`wait_confirm`** gets the same id-keyed guard: a re-emit for an
    already-placed id is skipped; a genuine new turn (fresh id) still places.
- **Hard rule honoured:** the fallback is *not* text-keyed hiding. The proof is
  the regression test below.

### Tests (regressions, both directions)

`agent-ui/src/lib/userTurnPlacement.test.ts`:
- **re-emitted confirm → one copy:** a confirm for an already-placed id is a
  re-emit; also detected from the placed copy when the id no longer resolves.
- **genuine second send, same text, different id → two copies:** a fresh id with
  the same text is **not** a re-emit (this is the case the old text guard got
  wrong).
- plus: unplaced id is new even when the same text is placed; first placement is
  not a re-emit; whitespace-normalised match; no match on text alone.

`agent-ui/src/store/userTurnPlacement.store.test.ts`:
- drives the real store: a migrated turn leaves no copy behind (exactly one copy
  across both tasks) and the `removeSource` path is a no-op when the source is
  absent.

`npx tsc -p tsconfig.build.json --noEmit` clean. `npx vitest run` for the new and
adjacent suites green (dedupe, projectStore except one pre-existing preview-shell
assertion, and the two new files).

### Known limitation (unchanged from §9.3)

The registry is in-memory, so it does not survive a reload mid-duplicate — but
the durable store is single-copy anyway, so a reload rehydrates clean. If
durability is ever wanted, seed the registry from the durable turn list on
hydrate (cold path).
