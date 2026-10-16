# Duplicate user turns in long chats — investigation memo

Status: **open / not root-caused.** This is a consolidated record so we stop re-deriving it each session.
Last updated: 2026-10-15.

Related code:

- `agent-ui/src/store/chatStore.ts`
- `agent-ui/src/lib/userTurnPlacement.ts`
- `agent-ui/src/lib/dedupeUserTurns.ts`
- `agent-ui/src/components/ChatBox/index.tsx`
- `agent-ui/src/hooks/useRemoteControlBridge.ts`

---

## 1. The symptom, stated precisely

A single user prompt shows up as **two user bubbles** in the conversation, and it gets
worse the longer the chat. It is *not* the prompt being sent to the backend twice
(the backend runs one turn). It is one logical user turn being **placed into two
task sections at once**.

Why that renders as a duplicate: the conversation timeline renders, and the export
prints, **one section per task**. A follow-up turn is optimistically added to the
current task, then the `confirmed` event creates a fresh task and the turn is
supposed to *migrate* into it. When the migration fails to delete the source copy,
the same turn exists in both tasks and both sections render.

So the whole bug reduces to one question:

> **When a turn is migrated from the source task into the new task, why does the delete of the source copy fail?**

Everything below is the answer candidates for that question.

---

## 2. The two guard layers (and the important fact that one is dead code)

There are **two** independent guards in the tree meant to prevent this. Only one is
actually wired in.

### Layer 1 — placement-time, ID-keyed (LIVE)

`agent-ui/src/lib/userTurnPlacement.ts`.

- `PlacedUserTurnRegistry` (`:43`) is an in-memory `Set` of turn ids that have been
  placed in their **final** task.
- `isReemittedUserTurn` (`:92`) returns true when a `confirmed`/`wait_confirm` is a
  re-emit of a turn we already placed. If the turn id resolves, it is a pure
  `registry.isPlaced(id)` check with no text comparison (`:98-100`). Only when the id
  can **not** be resolved does it fall back to: find a user message in the current
  task whose id is already placed and whose normalized text matches (`:102-110`).
- `resolveSourceUserTurnId` (`:119`) is the delete helper: prefer the message whose
  id equals the turn id; else fall back to the trailing user message **only if its
  normalized text matches** (`:130-137`); else `undefined`.
- `markPlaced` is called at exactly two sites: `chatStore.ts:2848` (confirmed path)
  and `chatStore.ts:3360` (wait_confirm path). Confirmed.
- `placedUserTurns.reset()` is called **only** in the test file
  (`userTurnPlacement.test.ts:176,180`). So it is a process-lifetime in-memory
  registry, never cleared at runtime.

### Layer 2 — render/export-time, text-keyed (DEAD CODE)

`agent-ui/src/lib/dedupeUserTurns.ts` exports `collectDuplicateUserTurnIds` (`:47`),
which walks the ordered task sections and returns the ids of consecutive duplicate
user turns (same text, no agent turn between).

**This function is imported nowhere in production code.** A grep for
`collectDuplicateUserTurnIds` returns only its own definition and its test. The only
thing the store pulls from that module is `normalizeUserTurnContent`
(`chatStore.ts:62`, `userTurnPlacement.ts:27`).

Consequence: there is **no render-time / export-time dedupe in effect.** The only
thing standing between a stuck source copy and a visible duplicate is the
placement-time delete. If that delete misses, the duplicate is guaranteed to show.
This is a real finding and a cheap possible mitigation (see §5).

---

## 3. The migration path, read end to end

Confirmed path, `chatStore.ts` `onmessage` → `confirmed` handling:

1. `sourceTurnId` = `previousChatStore.tasks[currentTaskId]?.nextUserId`, else the
   trailing message's id if it is a user turn, else `undefined` (`:2741-2745`).
2. Re-emit guard. If `isReemittedUserTurn(...)` is true, set `skipFirstConfirm = false`
   and **return** (`:2754-2764`) — no new task.
3. `carriedUserId = sourceTurnId || generateUniqueId()` (`:2766`).
4. `sourceTurnIdToRemove = resolveSourceUserTurnId(sourceMessages, carriedUserId, userMessageContent)` (`:2772-2776`).
5. `projectStore.appendInitChatStore(project_id, nextTaskId)` creates the new task (`:2779`).
6. `updateLockedReferences(newChatStore, newTaskId)` bumps the locked task forward
   (`:2789`) — the only call site.
7. The turn is added to the new task and the source copy (`sourceTurnIdToRemove`) is
   removed; `placedUserTurns.markPlaced(carriedUserId)` records it (`:2848`).

The critical outside dependency:

- `nextUserId` is written in **only two places, neither inside `chatStore.ts`**:
  `ChatBox/index.tsx:1120` (the normal send path) and `useRemoteControlBridge.ts:499`.
- It is read in `chatStore.ts` at `:2742` (from the **previous/source** task) and
  `:3316` (from the **current** task, in the wait_confirm path).
- **Nothing copies `nextUserId` into the destination task on migration, and nothing
  clears it on the source task.**

---

## 4. Candidate causes, with confidence

### Cause A — write site and read site disagree on the task id (STILL PLAUSIBLE, unproven)

`handleSend` records `nextUserId` on `_taskId` (`ChatBox/index.tsx:1120`). At confirm
time the store reads it from `currentTaskId` (`chatStore.ts:2742`). If, at the moment
the `confirmed` arrives, `currentTaskId` is no longer the task `handleSend` wrote to,
`sourceTurnId` is `undefined`. Then:

- `carriedUserId` falls back to `generateUniqueId()` (`:2766`), so
  `resolveSourceUserTurnId` cannot find the bubble by id and drops to the positional
  text fallback (`userTurnPlacement.ts:130-137`). If a notice / ack / the previous
  turn's `end` landed after the optimistic bubble, the fallback returns `undefined`
  and **the source copy is never removed.**
- `markPlaced(<generated id>)` (`:2848`) records an id no later event will ever
  produce, so the guard cannot catch the next delivery either.

Confidence: **medium.** Mechanism is real and unguarded; whether `currentTaskId` and
`_taskId` actually drift for the same turn is not proven.

### Cause B — same event delivered twice on two live streams (PLAUSIBLE, unproven)

The session is one long-lived SSE stream per **project**, but `activeSSEControllers`
is keyed by **task id** (`chatStore.ts:2403`). A new task id is minted on every
follow-up (`ChatBox/index.tsx:1112`) and the locked reference advances on every
`confirmed` (`:2789`), while the underlying stream/controller stays keyed under the
id it was opened with. The resume guard (`:2381-2400`), `stopTask`, 
`closeSSEConnectionsForTasks` (`:6575`) and `hasActiveSSEConnection` (`:6541`) all
look up by **task id**, so they can miss the real controller. Miss it and a follow-up
can open a **second consumer on the same project**, delivering the same `confirmed`
twice.

The one thing preventing that is `hasLiveSessionStream` (`:6553`), which is already
keyed by **project** (`:6557-6559`). It is a boolean over the map and can be falsely
cleared by the 90s stale reaper.

Confidence: **medium-low.** Best explanation for why it tracks turn count, but no live
trace.

### Cause C — the wait_confirm path has the same flaw more bluntly (HIGH, but narrower blast radius)

In the `wait_confirm` branch, `stableTurnId` is read from the **current** task
(`chatStore.ts:3316`). After a migration that current task is the *new* task, which
almost never has a `nextUserId`. So `stableTurnId` is `undefined`, the registry is
never consulted (`:3322`), and the code falls back to "replace the last user message
with matching text, else append" (`:3329-3336`). If the last message is not the user
turn with matching normalized text, the optimistic copy is **appended, not replaced**,
→ duplicate.

Confidence: **high that this branch is fragile**; whether it is *the* duplicate in a
given repro is unproven.

### Counter-evidence worth keeping honest

The re-emit guard for `confirmed` is more complete than a first read suggests. Walk
the pure double-delivery case:

1. First `confirmed` migrates the turn, sets `lockedTaskId = newTaskId`, marks
   `carriedUserId` placed.
2. Second delivery reads `nextUserId` from `newTaskId` (absent) → `sourceTurnId`
   `undefined` → `isReemittedUserTurn` drops to the fallback (`userTurnPlacement.ts:102-110`).
3. After migration the bubble exists in the current task **and is placed**, so the
   fallback returns **true** and the second copy is skipped.

So a *pure* re-emit looks covered, **provided `userMessageContent` normalizes to the
same string.** That narrows Cause A to the case where the task ids genuinely disagree,
which is not yet proven.

---

## 5. The one experiment that decides it (not yet run)

Static reading cannot separate A, B, and C. Tag every appended user message with
`(stream generation, event sequence, resolved carriedUserId)` and, when two identical
bubbles coexist, compare the tags:

- **Same tag** → one event delivered twice → **Cause B**. Neither placement fix helps;
  fix the stream keying.
- **Different tags** → two separate placements → **Cause A or C**. The id-carrying fix
  is right.

Then confirm the task-id match directly: log `_taskId` at `ChatBox/index.tsx:1120`
against `currentTaskId` at `chatStore.ts:2742` for the same turn.

Suggested instrumentation points: the top of the `confirmed` handler (log stream
generation, `lockedTaskId`, `currentTaskId`, `nextUserId`, resolved `carriedUserId`,
`sourceTurnIdToRemove`) and the `wait_confirm` branch (log `stableTurnId` and the
resolved `removeId`).

---

## 6. Fix options, mapped to cause

Cheap, low-risk, and independent of which cause it is:

1. **Carry the turn id into the destination task.** On migration, set the new task's
   `nextUserId = carriedUserId` (or key the `wait_confirm` guard off `placedUserTurns`
   instead of the destination task's `nextUserId`). Closes the write/read drift in
   Cause A and the blunt `wait_confirm` flaw in Cause C.
2. **Key the SSE controller by project, not task id** (it already is for
   `hasLiveSessionStream`). Closes Cause B and the second-consumer window.
3. **Wire in the render-time dedupe.** `collectDuplicateUserTurnIds` already exists and
   is tested but dead. Wiring it into the timeline render (and export) is a last-line
   defense that hides a stuck duplicate regardless of cause. Note the risk it was
   written to avoid: it must key on placed ids, not text alone, so it never hides a
   legitimate re-send of the same text.

Recommended order: run the experiment first. If it shows Cause B, do (2). If it shows
A/C, do (1). (3) is worth doing regardless as a backstop.

---

## 7. What we can and cannot state

Can state (verified in the tree today):

- The duplicate is a placement failure, not a double send.
- The placement guard is ID-keyed at the write site (`ChatBox`/`useRemoteControlBridge`)
  and position/text-keyed at the fallback read site, and nothing keeps the id in sync
  across the migration.
- `nextUserId` is never copied to the destination task and never cleared on the source.
- `collectDuplicateUserTurnIds` is dead code; there is no active render-time dedupe.
- The `wait_confirm` guard reads `nextUserId` from the wrong (post-migration) task.

Cannot state:

- Which of A / B / C actually fires in your repro. All three are consistent with
  "worse the longer the chat."
- That any single fix above removes the duplicate. Rough confidence that the id-carrying
  fix alone does it: ~50%, pending the experiment in §5.
