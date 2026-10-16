# Change & Regression Ledger — chat/stream work

Purpose: one place to answer *"what did we change, what could it break, and how do
we undo it"* — so if something misbehaves tomorrow we can point at a commit, not
guess. Append a new dated section per change; never rewrite history here.

- Repo: `undisclosed`, branch `upgrade/theia-1.76`
- HEAD at time of writing: `a4a6462` (2026-10-12)
- Uncommitted: `agent-ui/src/components/CodeAgentWorkspace/AgentPanelHistory.tsx`
- Untracked: `docs/plans/sse-relay-and-next-features.md`, this file

---

## 0. Timeline of the commits in play

| SHA | Date | Subject | Touches |
|---|---|---|---|
| `a4a6462` | Oct 12 | fix(chat_history): return feedback data from get_feedback_map | brain chat history |
| `a542fd8` | Oct 12 | feat(connectors): validate required MCP env fields before connect | connectors UI |
| `4bef3db` | Oct 11 | fix(chat): make user-turn placement idempotent to stop duplicated prompts | `ProjectChatContainer.tsx`, `ProjectSection.tsx`, dedupe tests |
| `57ad754` | Oct 11 | feat(skills): ship bundled example skills in the packaged app | skills assets |
| `4f9d8ee` | Oct 10 | fix(chat): recover dead streams and keep idle sessions alive | `chatStore.ts`, `ChatBox/index.tsx`, brain `chat_controller.py`/`chat.py`/`chat_service.py` |
| `7fe6770` | Oct 10 | fix: unblock stalled turns and nested scroll containers | chat UI |

The three that matter for regressions we are tracking: **`4f9d8ee`** and
**`4bef3db`** (both already shipped), plus the uncommitted history-sort change.

---

## 1. Change: history sort by recency  (uncommitted)

- **File:** `agent-ui/src/components/CodeAgentWorkspace/AgentPanelHistory.tsx`
- **What we are fixing:** the History list was ordered by *creation* time
  (`getVisibleProjectMetasForSpace`, `store/spaceStore.ts:255`). The chat you just
  used is usually an older project, so it sank below a freshly created, empty one.
- **What changed:** after the base list is built we `.sort()` a second time:
  float `lastVisitedProjectBySpace[activeSpaceId]` to the top, then order the rest
  by `updatedAt ?? createdAt` descending.
- **Why it is low risk:** `getVisibleProjectMetasForSpace` returns a **fresh**
  array (it is `Object.values(...).filter(...).map(...).sort(...)`), so the extra
  `.sort()` mutates a throwaway copy, not store state. No store writes, no API
  calls, no render-side effects.
- **Possible regressions:**
  - If `lastVisitedProjectBySpace[activeSpaceId]` points at a project that is
    filtered out (archived / auto-created), the float simply never matches and
    ordering falls through to recency. Safe.
  - Ties (`updatedAt` equal, or equal `createdAt` fallback) resolve stably in V8.
    Worst case two chats swap; not user-visible breakage.
  - `updatedAt` is populated by the server as turns land. If a project has no
    server timestamp, we fall back to `createdAt` (old behaviour for that row).
- **How to detect a regression:** History list order looks wrong / a chat you
  just messaged is not near the top / a pinned project disappeared. All of these
  are read-only; nothing is persisted by this change.
- **Rollback:** `git checkout -- agent-ui/src/components/CodeAgentWorkspace/AgentPanelHistory.tsx`
  (restores creation-order listing).
- **Verified:** type-check pending this pass; no store mutation (source-read).

---

## 2. The "disappearing message" and the `4bef3db` trade

Not a change we are making yet — the diagnosis behind the doc request.

- **Symptom:** after sending a follow-up, the user's bubble can vanish (and in one
  report the whole turn re-sent). Reachable *history* is intact on disk.
- **Mechanism:** the message is shown by two paths. The **durable** path appends
  the turn and POSTs it to the brain (`/api/v1/chat/...`, written under
  `~/.undisclosed/turns/<chatId>/`). The **live** path assembles the bubble from
  the SSE stream. When the live leg misses, the bubble is absent until the panel
  remounts and re-reads turns from disk — at which point the message "reappears".
- **Suspect commit:** **`4bef3db`** (Oct 11). It made user-turn placement
  idempotent to stop *duplicated* prompts, using a `collectDuplicateUserTurnIds`
  guard: "the same user text with no agent turn between can never be a legitimate
  repeat, so hiding the later copy is safe."
- **The regression trade:** that assumption is the whole risk. A legitimate repeat
  (same text sent twice on purpose, e.g. "retry", "continue", "yes") with no agent
  turn rendered in between will be **collapsed to one bubble**. So fixing the
  duplicate also introduced a *hide-a-real-message* failure mode.
- **Why it showed up now:** `4f9d8ee` (Oct 10) added a second stream per session
  (resume/attach) and a re-attach-on-follow-up watchdog. More stream events
  re-emitted `confirmed`/`wait_confirm`, which is exactly the path `4bef3db`
  dedupes — so the two commits interact.
- **How to detect:** send the same short text twice in a row with no agent turn
  between; if the second bubble is swallowed, this guard is the cause.
- **Candidate fix (the "re-read a turn" fallback):** on `confirmed`/`wait_confirm`,
  reconcile against the persisted turns for the chat before dropping a copy —
  i.e. only collapse when the turn id *and* the server turn record agree, rather
  than a pure text match. (Design only; not implemented.)
- **Rollback of the shipped commit if needed:** `git revert 4bef3db`
  (restores duplicated-prompt behaviour; do not do this without re-checking the
  duplicate bug first).

---

## 3. Change: SSE relay  (starting; flag-gated, OFF by default)

See `docs/plans/sse-relay-and-next-features.md` §1 for the full design.

- **What we are fixing:** the renderer opens SSE sockets **directly** against the
  brain host (`api/http.ts:335` `sseTransport` → `fetchEventSource`). Chromium caps
  HTTP/1.1 at 6 connections per host, and `4f9d8ee` made it **two** streams per
  session, so roughly **three** concurrent chats freeze the UI behind the cap.
- **What we will change:** move stream ownership to the Theia backend
  (`packages/undisclosed-agent/src/node/undisclosed-agent-backend-module.ts`) and
  give the renderer **one** multiplexed channel.
- **Guarantee:** the relay is behind `VITE_STREAM_RELAY` (a **build-time** Vite
  flag — see §7) and **defaults to off**, so the direct path is byte-for-byte
  unchanged until we flip it. That makes this "start" strictly additive: zero
  behaviour change on merge.
- **Possible regressions (when the flag is on):**
  - SSE frames mis-demultiplexed across `streamId`s → cross-talk between chats.
  - Auth/scope difference: the relay dials the brain from the backend, so requests
    that relied on the renderer's origin/headers must carry them explicitly.
  - Packaged app: the `file://` frontend must resolve the relay via `serverUrl()`,
    not a bare root-relative path.
  - Trigger execution streams also go through `sseTransport`; if they are not
    routed too, the cap returns via automations.
  - `heartbeat`/`sync` idle frames from `4f9d8ee` must survive the relay or idle
    sessions will look dead again.
- **How to detect:** flag off = no change at all. Flag on = watch for a chat
  receiving another chat's tokens, or idle sessions dropping after a few minutes.
- **Rollback:** set `VITE_STREAM_RELAY=off` (or unset) in `agent-ui/.env` and
  rebuild the embed (`npm run build:agent-ui`); or just revert the http.ts hunk.

---

## 4. Concrete defects found this pass

### R1 — stray NUL byte makes a source file binary  (introduced by `4bef3db`)

- **File:** `agent-ui/src/components/ChatBox/ProjectSection.tsx`, line 188.
- **What:** the dedupe key is built as a template literal that embeds a **raw 0x00
  byte** between `role` and `content`:
  `` `${role}<0x00>${typeof content === 'string' ? content : JSON.stringify(content ?? '')}` ``.
  It was almost certainly meant to be the escape `\u0000`, but the literal byte was
  typed/pasted instead.
- **Impact:** git treats the whole file as **binary** (that is why `4bef3db`'s stat
  reads `ProjectSection.tsx | Bin 16514 -> 17136 bytes`). No reviewable diff, and
  any tool that treats NUL as binary (some editors, patch tooling, CI diff steps)
  can misbehave on it. Runtime behaviour is unchanged (a NUL is a legal string
  char, same delimiter intent).
- **Fix:** write the escape `\u0000` in the source so the file is text again;
  runtime stays identical. Behaviour-preserving, one token.
- **How to detect recurrence:** `git diff --stat` showing `Bin ... bytes` for a
  `.ts`/`.tsx` file. Guard: `grep -rlP '\x00' agent-ui/src --include='*.ts*'`.
- **Rollback:** trivial (revert the one-line escape).

### R2 — history sort mutating store state?  NO

Checked because an in-place `.sort()` on a store-backed array would be a real bug.
`getVisibleProjectMetasForSpace` returns a freshly built array, so the added
`.sort()` cannot leak into the store. No action.

---

## 5. Rollback playbook (fast path)

1. **History order wrong** → `git checkout -- agent-ui/src/components/CodeAgentWorkspace/AgentPanelHistory.tsx`
2. **Duplicate prompts back** → revert `4bef3db` (watch: also re-arms the vanish/hide bug below)
3. **Message vanishes / legit repeat swallowed** → inspect `4bef3db`'s `collectDuplicateUserTurnIds` guard; the fix is server-reconciled dedupe, not text-only
4. **Chat UI freezes with several sessions open** → this is the connection-cap bug the relay targets; nothing to revert, it is pre-existing
5. **Relay misbehaving** → `UNDISCLOSED_STREAM_RELAY=off`

## 6. How to bisect

`4f9d8ee` and `4bef3db` are the only Oct 10–12 commits that touch chat
placement/streaming; everything else in the window is README, skills assets,
connectors validation, and a brain feedback-map fix. If a new symptom appears,
turn the flag off, then `git bisect` over `735bce3..a4a6462` with the two chat
commits as the prime suspects.

---

## 7. Turning the relay ON and knowing it's live

**Why "I set the relay env" did nothing.** The renderer checks
`import.meta.env.VITE_STREAM_RELAY === 'on'`. `import.meta.env.VITE_*` is a
**build-time constant** baked into the embed bundle — it is not read at runtime.
Two things meant the first attempt shipped nothing:

1. **Wrong file.** The flag was placed in the repo-root `.env`. The agent-embed
   build is a Vite build whose `envDir` is `agent-ui/` (no `envDir` override in
   `agent-ui/vite.config.agent-embed.ts`), so Vite only reads `agent-ui/.env`.
   The root `.env` is the brain/Theia file; Vite never sees it here.
2. **Not rebuilt / tree-shaken.** Because the flag was `undefined` at build time,
   the minifier constant-folded `isStreamRelayEnabled()` to `false` and dropped
   the whole relay client. Proof: the old bundle had **0** occurrences of
   `undisclosed-agent/relay`; after the fix it has `relay/events`, `relay/open`,
   `relay/abort`.

**Fix applied:** created `agent-ui/.env` (git-ignored) with
`VITE_STREAM_RELAY=on`, then rebuilt + synced (`npm run build:agent-ui`, which
runs the embed build and copies `agent-embed.umd.js` into
`packages/undisclosed-agent/assets/agent-embed/`).

**To test / verify in the dev editor:**

1. **Backend restart** (once). The relay routes live in the Theia backend
   (`packages/undisclosed-agent/lib/node/undisclosed-agent-backend-module.js`);
   the dev backend does not hot-reload node code, so restart the editor/backend
   after `npm --prefix packages/undisclosed-agent run build`.
   - Ping it: `curl -N http://localhost:3000/undisclosed-agent/relay/events`
     should stream `: relay-connected` then `: ping` every 15s. If it 404s, the
     backend restart didn't take.
2. **Reload the panel** (browser reload, no full app rebuild). The bundle is
   served from `/undisclosed-agent/agent-embed.umd.js`, so a page reload picks up
   the new one.
3. **Confirm the flag is live**: in devtools console,
   `import.meta.env` isn't exposed at runtime, so check behavior instead —
   **Network tab** should show ONE long-lived
   `GET /undisclosed-agent/relay/events` (type `eventsource`) plus a short
   `POST /undisclosed-agent/relay/open` per turn, and **no** direct
   `GET/POST http://localhost:5001/...` SSE from the renderer. With the flag off
   you instead see the renderer dialing `:5001` directly.
4. **Functional check:** open 3+ chats and start runs in each. With the relay on
   they no longer fight over Chromium's 6-connections-per-host cap, so the UI
   keeps streaming; with it off the 3rd+ session starves and the panel looks
   frozen (the original bug).
5. **Leak check:** chat A's tokens must never appear in chat B. If they do, the
   `streamId` demultiplexing in `pumpRelayBuffer` is wrong — report it, don't
   keep it on.

- **Rollback:** `VITE_STREAM_RELAY=off` (or remove) in `agent-ui/.env` +
  `npm run build:agent-ui`. Instant, no backend change.
- **Possible regressions while on:** mis-demux cross-talk; the relay dialing the
  brain from the backend drops origin-only headers (must be re-sent explicitly);
  idle `heartbeat`/`sync` frames must survive the relay or idle sessions look
  dead; trigger execution streams also go through `sseTransport` so they get the
  same path (good) — verify after Automations is exercised.

---

## 8. Change: Automations (triggers) surfaced in the editor panel

- **What we are fixing:** the trigger backend (`/api/v1/trigger/*`) and the full
  `components/Trigger` UI already exist and are wired on the classic
  `pages/Workspace.tsx`, but the **embedded/editor panel** had no `triggers`
  body, so automations were unreachable from the Theia sidebar. This is a
  surfacing change, not new behavior.
- **Files added:** `agent-ui/src/components/CodeAgentWorkspace/AgentTriggers.tsx`
  — a thin, self-contained wrapper that owns the page-level UI state
  (sort key, selected trigger, execution-logs drawer, create dialog) and renders
  the existing `<TriggerPanel>`; reuses the shared
  `EXECUTION_LOGS_OPEN_STORAGE_KEY` so the drawer preference is consistent with
  the workspace.
- **Files changed:**
  - `agent-ui/src/agent-embed/AgentEmbedPanel.tsx` — new `'triggers'` body +
    `showTriggers()` on `AgentPanelApi` + render branch in `ManagedScreen`.
  - `agent-ui/src/agent-embed/mount.tsx` — expose `showTriggers()` on the handle.
  - `agent-ui/src/agent-embed/embedNav.ts` — add `'triggers'` to `EmbedScreen`.
  - `packages/undisclosed-agent/src/browser/undisclosed-agent-contribution.ts` —
    `undisclosed-agent.triggers` command + "Automations" item in the `⋯` menu.
  - `packages/undisclosed-agent/src/browser/undisclosed-agent-widget.tsx` —
    `showTriggers()` delegate on `AgentPanelHandle`.
- **Why it is low risk:** no store or API changes; it mounts components that
  already ship, behind a menu item that only a visible agent widget enables. The
  panel body guard (`isVisible: (w) => !!asAgent(w)`) matches every sibling item.
- **Possible regressions:**
  - The `⋯` menu now has an extra row; if ordering looks off, adjust the
    `order: '1.45'` in `registerMenus`.
  - `AgentTriggers` reuses the shared execution-logs localStorage key, so toggling
    the drawer in either surface follows you into the other. Expected.
  - `TriggerPanel` needs an active project to fetch; with no active workspace
    folder the list is empty (same as the workspace page). Not a crash.
- **Detection:** Automations missing from the `⋯` menu; clicking it blank-screens
  the panel; or the drawer/e dialog not opening. All read-only until you create a
  trigger.
- **Rollback:** `git checkout -- agent-ui/src/agent-embed/AgentEmbedPanel.tsx
  agent-ui/src/agent-embed/mount.tsx agent-ui/src/agent-embed/embedNav.ts
  packages/undisclosed-agent/src/browser/undisclosed-agent-contribution.ts
  packages/undisclosed-agent/src/browser/undisclosed-agent-widget.tsx` and delete
  `AgentTriggers.tsx`.
- **Open gap (NOT fixed by this change):** the trigger **execution runtime**
  (`useExecutionSubscription` WebSocket + `useTriggerTaskExecutor` +
  `useBackgroundTaskProcessor`) is mounted in `agent-ui/src/App.tsx`, which the
  embed does not render. So from the editor you can create/enable/schedule
  triggers and read execution logs, but a fired trigger will not auto-run a task
  in the embedded panel until that runtime is mounted in the embed. That has its
  own risk (the WS URL is built from `import.meta.env.VITE_BASE_URL` /
  `VITE_PROXY_URL`, also build-time), so it is a deliberate separate step.
- **Verified:** `npx tsc -p tsconfig.build.json --noEmit` (agent-ui) → 0;
  `npm --prefix packages/undisclosed-agent run build` (tsc) → 0; `npm run
  build:agent-ui` → bundle contains the Automations screen and the relay routes.

---

## 9. Session 2026-10-12 (evening): relay out, chat regression reverted, triggers backend

### 9.1 SSE relay removed (uncommitted work reverted)

- **Files reverted to HEAD:** `agent-ui/src/api/http.ts` (-288 lines),
  `packages/undisclosed-agent/src/node/undisclosed-agent-backend-module.ts`
  (-188 lines, the `/undisclosed-agent/relay/*` routes).
- **Flag:** `agent-ui/.env` `VITE_STREAM_RELAY=off` (was `on`).
- **Rebuilt** the embed (`npm run build:agent-ui`); bundle has 0 `undisclosed-agent/relay`
  references. Backend package `tsc` clean.
- **Why:** the relay (on) regressed new chats — "stuck on preparing agent". The
  direct-to-brain path is restored, byte-for-byte, to pre-relay.
- **Rollback:** re-apply the two files + set the flag `on` + rebuild.

### 9.2 Chat "disappearing" — selective revert of `4bef3db`

Reverted ONLY the render/export **hiding** guard the commit introduced (the code
that *hides* a user bubble, which is worse than a duplicate: it can drop the
whole task section that carries the agent's answer):

- `agent-ui/src/components/ChatBox/ProjectChatContainer.tsx` → `4bef3db^`
- `agent-ui/src/lib/exportChat.ts` → `4bef3db^`
- `agent-ui/src/components/ChatBox/ProjectSection.tsx` → `hiddenUserMessageIds`
  prop + filter removed (kept the `\u0000` content-key fix so the file stays text).
- **Kept** from `4bef3db`: the stable user-turn id (`setNextUserId`), the
  `confirmed` idempotency, and `appendInitChatStore`'s task-id idempotency.
  `dedupeUserTurns.ts` remains (used by `chatStore`); `collectDuplicateUserTurnIds`
  is now unused by app code (tree-shaken from the bundle).
- **Rollback:** `git checkout HEAD -- ...ProjectChatContainer.tsx ...exportChat.ts`
  and re-add the ProjectSection prop+hiding, or `git revert` this hunk.

### 9.3 Automations backend (fixes the `/api/v1/trigger` 404)

The local Brain had **no** trigger router at all (that surface lived in the
upstream cloud server), so every Automations call 404'd.

- **Added** `brain/app/controller/trigger_controller.py`: JSON-backed CRUD +
  executions + `WS /execution/subscribe` + a 5-field-cron scheduler thread.
  Storage: `~/.undisclosed/triggers/store.json` (override
  `UNDISCLOSED_TRIGGERS_ROOT`).
- **Routes** (mounted at `/api/v1` in `brain/app/router.py`): `GET/POST /trigger/`,
  `GET /trigger/{type}/config`, `GET/PUT/DELETE /trigger/{id}`,
  `POST /trigger/{id}/activate|deactivate`, `GET /trigger/{id}/executions`,
  `PUT /execution/{id}`, `POST /execution/{id}/retry`, `WS /execution/subscribe`.
- **Verified:** `py_compile` clean; TestClient CRUD smoke test passes; cron
  match/next-run + scheduler firing tested; WS connect/subscribe/ping tested;
  routes register at `/api/v1` under `register_routers`.
- **Known gap (not done here):** Slack/Webhook delivery is modelled (config +
  webhook URL + status) but only `schedule` triggers self-fire. The editor's
  `/api` proxy is HTTP-only (`http-proxy` `proxy.web`, no `upgrade`), so the
  execution WS may not traverse it from the editor origin — verify before relying
  on live execution streaming in the embed.

### 9.4 Create-trigger modal "not of this world"

- **File:** `agent-ui/src/components/ui/dialog.tsx`.
- Radix portals to `<body>`, which is OUTSIDE `.undisclosed-agent-root` (where the
  embed stylesheet scopes its preflight/`*` resets) and UNDER the host editor's
  high-z chrome. The dialog therefore rendered with the host's element styling.
- **Fix:** `DialogContent`'s portal now targets a body-level container that carries
  `undisclosed-agent-root` and sits at a very high `z-index` (click-through while
  empty, with overlay/content opting back in via `pointer-events-auto`). Outside
  the embed the helper returns `undefined`, so the standalone app is unchanged.
- **Rollback:** revert `dialog.tsx`.
