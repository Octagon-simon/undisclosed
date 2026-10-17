# Multiple Editors, One Brain — Plan

Status: **proposal, for review before implementation.**
Goal (yours): have several editors open at once, all driving the same brain,
without one starving the others or the UI losing its icons.

Last verified against: working tree with the skills split (brag/video skills
de-vendored from the repo; installed on demand from upstream), 2026-10-15.

---

## 0. TL;DR

- **Your setup runs one brain for all editors on purpose.** Root `.env` sets
  `UNDISCLOSED_BRAIN_SELF_HOSTED=1`, so no app spawns or adopts a brain; you run
  it yourself (`scripts/brain.sh start` on `127.0.0.1:5001`) and every editor
  connects to it. That is the shared brain you want.
- **The brain is single-process, single-event-loop.** `brain/main.py:307` builds
  `uvicorn.Config(api, host, port)` with **no `workers=`**, so every chat in
  every editor lands on one event loop. One long turn blocks the rest. This is
  the "brain runs in one editor, won't respond in the others" symptom.
- **The SSE relay does NOT fix this and is not even in the build.** It was
  reverted 2026-10-12 and `VITE_STREAM_RELAY=off` in `agent-ui/.env`. The `on`
  you have in the **root** `.env` is inert: Vite reads `agent-ui/.env`, not the
  repo root, so nothing changed when you flipped it.
- **Three separate problems are tangled together** (below). Only one of them is
  about multiple editors. Fixing them as one blob is why previous attempts
  regressed.
- **Recommendation:** pick the product shape first (one app, many windows vs.
  truly separate instances). That choice decides almost everything else.

---

## 1. Current state, grounded in the code

### 1.1 One external brain, by choice
- `brain-launcher.ts:116` `selfHosted()` returns true for
  `UNDISCLOSED_BRAIN_SELF_HOSTED=1`; `onStart()` (`:130`) then logs and returns,
  so the launcher never spawns, never watchdogs, never adopts. Your root `.env`
  sets this to `1` (line 15).
- Consequence: the single-owner guard (`portInUse` at `:23`, defer branch at
  `:155`) is a **no-op in your setup**. It only matters when the app manages a
  brain. It is not the thing keeping you safe or unsafe here.
- `brain/main.py:270` binds `127.0.0.1` (not `0.0.0.0`) exactly so a second brain
  cannot silently co-exist. Good: one brain, one port.

### 1.2 The brain is single-threaded
- `brain/main.py:307` `uvicorn.Config(api, host=host, port=port, ...)` — no
  `workers`, no `--factory`. One worker = one process = one event loop.
- Worker-pool fixes are not drop-in: the agent session/state lives **inside that
  process** (the reload comment at `:280` and `brain-launcher.ts` comments both
  say so). `workers=N` would give each worker its own in-memory state and break
  session continuity. Treat multi-worker as a redesign, not a config flag.

### 1.3 The relay is reverted
- No `relay` references remain in `packages/undisclosed-agent/src` (grep is
  empty).
- `agent-ui/.env:10` `VITE_STREAM_RELAY=off`, with a comment recording the
  revert: the relay regressed new chats (stuck on "preparing agent").
- `docs/changes/2026-10-12-chat-stream-change-ledger.md` records the rollback.
- Direct-to-brain SSE is back: `sseTransport()` at `agent-ui/src/api/http.ts:335`,
  consumed from `chatStore.ts:2505`.

### 1.4 Single-instance lock is already on
- `apps/desktop/src-gen/backend/electron-main.js:98` sets
  `isSingleInstance = true` and calls `app.requestSingleInstanceLock(process.argv)`
  at `:100`; a second launch of the same app identity quits.
- So "3 editors" is not 3 copies of the same packaged app under one identity
  unless the userData differs. Figure out **what the 3 editors actually are**
  (see §5, Q1). This matters: it decides whether you even need a cross-process
  fix.

---

## 2. Three problems, not one

Keep these separate. They have different causes and different fixes.

**A. Cross-editor brain contention (server-side).**
N editors open turns against one event loop. A long turn (or a stuck one) blocks
every other editor. Symptom: "the brain answers in one editor but not the
others." Killing the other editors "fixes" it because contention drops.
Fix lives in the brain (concurrency / queueing / per-session isolation), not in
the UI.

*Observed instance (this session).* The brain froze mid-task; the user's message
was sent more than once because the UI had no response, then after a manual
`brain.sh` stop/restart the last message was re-sent. That is A behaving exactly
as described: a stalled brain does not refuse work, it just stops answering, so
the client retries and the same turn is delivered repeatedly. See also
`docs/plans/duplicate-user-turn-in-chat-and-export-plan.md` for the duplicate-turn
handling side.

**B. Per-editor connection saturation (client-side).**
Within **one** editor, each live chat holds ~2 long-lived SSE sockets straight to
the brain. Chromium caps HTTP/1.1 at 6 connections per host, so ~3 live chats in
a single editor saturate the pool and the UI looks frozen. This is the bug the
SSE relay was built for. It is a different failure from A.

**C. Missing icons/logos (the Theia plugin host).**
File icons are generated into the agent-ui bundle
(`agent-ui/src/assets/fileIcons.generated.ts`) and are not fetched at runtime, so
this is **not** a brain issue. `.theia-server.log` has 37
`plugin-host ERROR Error: Could not read message start ... <MessageStart>` entries
(e.g. `:267476`, `:278019`), i.e. a **binary RPC stream desync** in the plugin
host while it enumerates files under `node_modules`/`dist`. That kind of desync
drops extension-contributed UI, icon themes included. Three Electron apps also
starve each other of memory/IO, which is a plausible aggravator. Strong
candidate, not proven.

---

## 3. Does the (reverted) SSE relay fix your multi-editor problem?

**No.** It addresses B (renderer connection cap inside one editor). It does
nothing for A (cross-editor event-loop contention), which is your reported
symptom. It is also currently absent from the build, so it is a non-factor today.

---

## 4. Options

Each option says what it fixes and what it costs.

### Option 1 — One app instance, many windows (smallest change)
Lean on the existing single-instance lock and make "another editor" mean another
**window/workspace of the same running app** instead of another process.
- Fixes: duplicate app processes, orphan brains, port races, doubled resource
  use (helps C's starvation angle).
- Does not fix: A or B — every window still has its own renderer pool and still
  shares the one event loop.
- Cost: low. Mainly a UX/flow change plus making secondary windows first-class.

### Option 2 — Make the brain actually concurrent
Give the brain more than one execution lane.
- Sub-option 2a: run multiple uvicorn workers. **Blocked** by in-process session
  state (§1.2) unless you first externalize that state.
- Sub-option 2b: keep one process but run each session's agent turn on a worker
  thread / separate event loop, with a bounded concurrency limit and a queue.
  This is the realistic path. Needs an audit of what the agent tour touches that
  is not thread-safe (global registries, singletons, the tool RAG cache).
- Sub-option 2c: a scheduler/queue so editors' turns are fair instead of
  first-come-blocking.
- Fixes: A directly.
- Cost: medium to high. This is the real engineering work.

### Option 3 — Isolate per editor
Give each editor its own brain (distinct `UNDISCLOSED_BRAIN_PORT`, distinct
data dir).
- Fixes: A perfectly, by removing sharing entirely.
- Loses: the whole point (no shared memory/context), and multiplies memory, since
  the frozen brain is ~259 MB and each instance re-loads models.
- Cost: low to build, high to live with. Listed for completeness.

### Option 4 — Port the SSE relay properly
Re-implement the multiplexed relay (renderer → Theia backend → one upstream
socket per stream).
- Fixes: B.
- Prerequisite: fix the "preparing agent" handshake regression that caused the
  revert **first**, or you re-land a known-broken feature.
- Cost: medium. `docs/plans/sse-relay-and-next-features.md` §1 already sketches
  the concrete port.

### Option 5 — Multiplexing gateway in front of the brain
A single sidecar owns the brain and multiplexes N editor connections into it,
adding queueing/fairness at the boundary.
- Fixes: A at the transport layer without rewriting the agent.
- Cost: medium. New moving part to run and supervise; overlaps with 2c.

---

## 5. Open questions to research first

1. **What are the "3 editors," exactly?** Same packaged app launched twice
   (needs different userData to bypass the single-instance lock), a dev build +
   a packaged build, or multiple windows of one app? Everything downstream
   depends on this. Reproduce and record `ps` + the userData path of each.
2. **Where does the time actually go when it hangs?** When editor B is
   unresponsive, is the brain's event loop busy (CPU) or idle (blocked on a
   socket / deadlocked)? Capture a `py-spy dump` of the brain PID at the moment
   of the hang. This distinguishes A from a provider-request stall.
3. **Is the freeze reproducible with N identical "hello" turns**, or only with
   heavy turns? That tells you contention vs. a single long turn.
4. **Does the plugin-host desync correlate with load?** Grep
   `.theia-server.log` timestamps around the icon loss; check whether a
   file-watch storm (`node_modules`, `dist`) precedes it.
5. **What state is actually global in the brain?** Enumerate singletons/module
   globals the agent turn touches. This sizes Option 2b.

---

## 6. Recommended sequencing

1. **Reproduce + instrument (Q1–Q3).** Do not pick a fix before you know which of
   A/B/C you are looking at. ~half a day.
2. **Decide the product shape** (Option 1 vs. true multi-instance). This is a
   product call, yours.
3. **If multi-instance is the goal:** Option 2b/2c (real brain concurrency) is
   the load-bearing fix. Treat multi-worker as out of scope until state is
   externalized.
4. **Independent of the above:** Option 4 (relay) is still worth doing for
   single-editor chat concurrency, but only after the handshake regression is
   understood. It is not on the critical path for your current symptom.
5. **Separately, file the plugin-host desync (C)** as its own bug with the log
   evidence; don't fold it into the multi-editor work.

---

## 7. What I have NOT verified

- I have not reproduced the freeze under a controlled N-editor test.
- The plugin-host desync is a **strong candidate** for the missing icons, not a
  proven cause.
- I did not run the brain under a profiler, so "one event loop blocks the rest"
  is read from the code (`brain/main.py:307`, no `workers=`), not measured live.
- I have not re-fetched upstream for any PRs referenced in the SSE plan.
