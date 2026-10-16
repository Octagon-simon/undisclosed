# SSE Relay + Next-Feature Plan

Status: proposal, for review before implementation.
Target repo: this fork (`eigent-theia`), head basis `447b42b8` plus the
Oct 10–12 chat commits.

---

## 0. Order of work (my recommendation)

1. **SSE relay** (section 1). Real bug today: concurrent sessions starve the UI,
   and it removes the renderer from the fragile direct-to-brain path.
2. **Settle web/standalone vs desktop** (section 5.0). It gates how the relay is
   wired and how much of upstream we can track instead of fork.
3. Then feature work in this order: durable tasks/resume (2) → workspace bundles
   (3) → scoped memory + task queue (4) → model config (5) → skills/connectors
   (6) → automations surfaced in the editor (7).

---

## 1. The SSE relay

### 1.1 The problem, grounded in this repo

Stream consumption lives in the renderer and talks to the brain **directly**:

- `agent-ui/src/api/http.ts:335` `sseTransport()` calls
  `fetchEventSource()` (`@microsoft/fetch-event-source`, imported at `:26`).
- The url is built from `getBaseURL()` (the brain origin, CORS-open), not the
  Theia backend proxy. So the browser opens its SSE sockets against the brain
  host, not the editor origin.
- Consumers: `agent-ui/src/store/chatStore.ts` (~`:5041`–`:5168`) for the live
  chat stream, and `useExecutionSubscription.ts` for trigger executions.

Two facts combine badly:

- Each chat session holds **two** long-lived SSE streams (a live stream plus a
  resume/attach stream after the Oct 10 `4f9d8ee` resume-mode change).
- Chromium caps HTTP/1.1 at **6 connections per host**. Six streams = about
  **three** concurrently live chats before a new stream is queued behind the
  cap and the UI looks frozen.

We also have our own failure surface on the same path: the `/api` proxy in
`packages/undisclosed-agent/src/node/undisclosed-agent-backend-module.ts`
(`:254`, and the one-shot 502 + GET-retry logic at `:215`).

### 1.2 What upstream #2024 does

It moves stream consumption **off the renderer into the main process**. The main
process owns the upstream sockets; the renderer receives events over a single
IPC/relay channel. Net effect: N sessions no longer cost N×(2) renderer
connections against the brain host; they cost one channel.

### 1.3 The port for *this* repo (concrete)

We don't have a separate Electron main file for UI traffic to reuse directly —
our node side is the Theia backend module
(`packages/undisclosed-agent/src/node/undisclosed-agent-backend-module.ts`).
So the relay is a new contribution in that module plus a thin renderer client:

1. **Backend: one multiplexed channel.** Add a `GET /undisclosed-agent/relay`
   WebSocket (or a single long-lived SSE response) that:
   - accepts `open`/`abort` frames keyed by a client-generated `streamId`;
   - opens exactly one upstream `http.request` to the brain per `streamId`
     (loopback connect is cheap; keep no idle keep-alive, mirroring the
     `BRAIN_PROXY_AGENT` reasoning at `:104`);
   - forwards upstream bytes as `data` frames and terminal state as `close`
     frames.
   Mounted in `configure(app)` next to the existing `/api` proxy and
   `/undisclosed-agent` static mount.
2. **Renderer: swap the transport, not the consumers.** Rewrite
   `sseTransport()` (`api/http.ts:335`) to open/attach to the relay channel and
   feed parsed SSE messages into the same `onmessage`/`onerror`/`onclose`
   callbacks. `chatStore.ts` and `useExecutionSubscription.ts` stay untouched.
   Keep the old direct path behind a flag
   (`VITE_STREAM_RELAY=off`, a build-time flag in `agent-ui/.env`) so we can bisect.
3. **Reconnect/heartbeat.** Reuse the idle `sync` heartbeat from `4f9d8ee`;
   the channel reconnects once and re-attaches each `streamId`.
4. **Packaged app.** The relay must be reachable from the packaged
   `file://` frontend, so resolve it through `serverUrl()` (the same helper the
   widget uses for the bundle) rather than a bare root-relative URL.

### 1.4 Risks / unknowns

- WebSocket through the Theia backend works in dev and packaged; confirm against
  the Electron frontend proxy before building the fan-out.
- Trigger execution streams also go through `sseTransport`; route them too or
  the cap returns via triggers.
- I have **not** re-read upstream #2024's exact IPC shape this turn; the steps
  above are the repo-local design, not a line-for-line port. Confirm against the
  PR before implementing.

---

## 2. Durable tasks + resume after restart/reload

**What "durable" has to mean here.** A task must survive (a) the brain
restarting mid-turn, (b) the editor reloading, (c) the app quitting.

**What already exists (partial):**

- Turn durability on disk: `brain/app/controller/chat_history_controller.py`
  writes `~/.undisclosed/turns/<chatId>/turn_<queryId>.json` atomically; the
  editor re-reads it on mount (`ProjectSection.tsx:118` → `list_turns`).
- Resume **within a process**: `4f9d8ee` added `resume` mode to `POST /chat`
  and `task_lock.active_stream_id` so exactly one consumer drains the queue, plus
  a client liveness watchdog (`chatStore.ts`) that re-attaches a resume stream
  before a follow-up.

**What's missing:**

- **Task state is in memory.** The queue/plan/step state lives in the brain
  process (`task.py`, `single_agent_service.py`). A brain restart loses the
  in-flight task even though the turn files survive.
- **No task journal.** Nothing records "step 3 of 7 completed, resume at step 4".

**Design:**

- Persist the task record next to the turns:
  `~/.undisclosed/tasks/<chatId>/<taskId>.json` (status, plan, steps done,
  queue, last event seq). Write it the same atomic way the turn logger does.
- On startup, the brain scans for tasks in `running` state with no live
  consumer and either (a) resumes them if the step is idempotent, or (b) marks
  them `interrupted` for the editor to offer Resume.
- The editor already has the read-back fallback; extend it to also GET
  `/api/v1/chat/{chatId}/tasks/{taskId}` and reconcile on mount, so a reload
  shows the correct step, not a restarted-from-zero card.

---

## 3. Workspace Bundles (#1842)

A bundle = a reusable, versioned package of agent config: system prompt/agents,
skills, MCP/connectors, model profile, permissions. The point is to move the
per-project ad-hoc setup into something you can check in and share.

For us that mostly means a **serialization of what today is scattered across
stores**: `spaceStore`, the skills screen (`AgentSkills`), connectors
(`AgentConnectors`), model config (`AgentModels`), and the brain's permission
model. Sketch:

- `bundle.json` schema: `{ schemaVersion, agents[], skills[], connectors[],
  modelProfile, permissions }`.
- Store as a **git-backed** space artifact (upstream ties bundles to Spaces with
  version history) so a bundle has diffs and checkpoints.
- Editor surface: a "Bundle" picker in the panel that applies a bundle to the
  active space; export the current space as a bundle.

---

## 4. Scoped memory + task queue

**Scoped memory.** Upstream splits memory into User / Space / Session scope. We
already store and propagate scope: records carry `scope_type`/`scope_id`/`user_id`
and are carried forward into v2 on supersede (see the `memory_scope_propagation`
note). What's missing is the **UI and read path**: `AgentMemorySettings` shows a
flat list. Add a scope selector (User / this Space / this Session) and filter the
retrieval by the active scope. Memory write/extract stays as-is
(`llm_extract_turn_gate`, run-end pass).

**Task queue.** Upstream lets you reorder queued items and opt into a parallel
Session preview. We already have a queue (the `task_lock`/active-stream model
from `4f9d8ee`) and a queued-message UI (`removeQueuedMessage` in
`ProjectChatContainer`). Add: drag-to-reorder, and a "parallel" toggle that lets
a second session consume independently instead of the single-drainer lock.

---

## 5. Model config (#1954)

Today: `AgentModels` + the brain's provider settings, validated via
`fetchPostWithTimeout`. Upstream's model config is a first-class record (named
profiles you can bind to an agent/bundle), plus new providers (Meta Model API /
Muse Spark #1904, GPT-6 Sol thinking-effort levels #2030, Atlas Cloud #2047).

Sketch for us:

- Promote the current model selection to a **named profile** object
  (`{ id, name, provider, model, thinkingEffort, params }`).
- Bind a profile per-space and per-bundle (section 3), with the panel's model
  picker selecting the active profile instead of a raw model id.
- Add `thinkingEffort` to the request body where the provider supports it.

### 5.0 The web/standalone decision (do this early)

Upstream #2014 put brain control routes behind a local "Desktop capability"
credential (`require_local_control_if_configured`). Non-Electron builds run
without it. **Aligning our fork to upstream's `build:web` path is what keeps our
`/api` proxy working and stops us forking the brain.** Decide this before the
relay, because the relay's auth path depends on it. Watch #2045 and #1912.

---

## 6. Skills / Connectors redesign

Today: `AgentSkills` and `AgentConnectors` are separate managed screens
(`AgentEmbedPanel.tsx:229` and `:236`). We just shipped bundled example skills in
the packaged app (`57ad754`) and added MCP env-field validation before connect
(`a542fd8`).

Redesign direction:

- Unify into one "capabilities" surface: a skill and a connector are both things
  the agent can be granted, differing only by transport. One list, one enable
  toggle, one permission chip each.
- Bind capabilities to bundles/agents (section 3) so enabling is declarative,
  not per-session.
- Keep the connect-time validation we just added; surface the missing env field
  inline in the unified list.

---

## 7. Automations (#2016)

We **do** have the backend and a full component set — it's just not surfaced in
the editor panel:

- Backend: `/api/v1/trigger/` (list/get/config/create/update/delete/activate/
  deactivate/executions) via `agent-ui/src/service/triggerApi.ts`.
- UI already built: `components/Trigger/` (`TriggerDialog`, `Triggers`,
  `ExecutionLogs`, `TriggerListItem`), `components/Dispatch/`,
  `store/triggerStore`, `useExecutionSubscription`, `useTriggerTaskExecutor`.
- It's reachable from the classic app (`pages/Workspace.tsx` mounts
  `TriggerPanel`, `pages/Home/Triggers.tsx`), but the **editor-first panel**
  (`AgentEmbedPanel` / `RightAgentPanel`) has no `body === 'triggers'` branch —
  only conversation/history/skills/connectors/memory/models/settings/browser/
  stats.

So "automations" for us is mostly **surfacing**, not building:

- Add a `body === 'triggers'` screen to both panels wrapping the existing
  `components/Trigger` in `ManagedScreen`, exactly like the skills/connectors
  branches.
- Reuse `TriggerDialog`'s "turn this task into a schedule" entry point from the
  task completion card (`TaskCompletionCard.tsx` already imports it).
- Route trigger execution streams through the relay (section 1.4) so schedules
  don't reintroduce the connection cap.

My take: this is the highest value-per-effort item on the list, because the work
is already done and just needs a panel branch.

---

## 8. Sequencing summary

| Step | Item | Why first/later |
|---|---|---|
| 1 | SSE relay | live bug; also de-risks triggers/streams |
| 2 | web/standalone decision | gates relay auth + upstream tracking |
| 3 | Durable tasks + resume | correctness of long runs |
| 4 | Bundles | unlocked by 3's persistence |
| 5 | Scoped memory + queue | UI over existing model |
| 6 | Model config profiles | depends on bundles for binding |
| 7 | Skills/Connectors unification | depends on bundles |
| 8 | Automations surfaced | cheap; independent, can jump the queue |

(Carried caveat from the earlier diff: upstream PR numbers here are the
earlier-verified set; I did not re-fetch upstream this turn. Re-confirm each PR
before porting.)
