# Automations: Server-Side Executor — Scope

Status: proposal, for review before implementation.
Target repo: this fork (`eigent-theia`).
Follows the Slack-automation work: the trigger/execution backend surface and the
Slack Socket Mode listener are in place; what remains is *who runs the task*.

---

## 0. The one-line problem

A trigger fires, the brain records a **pending** execution, and then it waits for
a **UI** to run the task and report back. If no editor/panel is attached and
draining that execution, the automation does nothing. "Automations run
client-side" means exactly this: the brain creates work but never picks it up.

---

## 1. What happens today (grounded in this repo)

### 1.1 The brain fires, but does not run

All three fire paths live in `brain/app/controller/trigger_controller.py` and end
the same way: create a pending execution, broadcast an event, stop.

- Scheduler: `_run_due_schedule_triggers()` (~`:538`) → `_create_execution(...)`
  (status `EXEC_PENDING`) → `broadcast(_execution_created_event(...))`.
- Slack: `dispatch_slack_event()` (~`:476`), called by
  `brain/app/service/slack_socket_listener.py`, does the same.
- Generic webhook: `receive_webhook()` (~`:861`), same.

`_create_execution` (`:423`) is the only thing that writes an execution, and it
never moves it past `pending`. `broadcast()` (`:358`) pushes
`execution_created` onto `ws_router` clients at `/execution/subscribe` (`:370`).
Nothing in the brain consumes that event.

### 1.2 The client is the executor

The event is consumed entirely in `agent-ui`:

1. `hooks/useExecutionSubscription.ts` — WS client for `/execution/subscribe`;
   puts the event into `store/triggerStore.ts` (`webSocketEvent`).
2. `hooks/useTriggerTaskExecutor.ts` — on a new event, formats the message
   (`store/triggerTaskStore.ts` `formatTriggeredTaskMessage`, `:70`), ensures the
   target project exists (loads from history or creates one), and appends to
   `projectStore.queuedMessages`.
3. `hooks/useBackgroundTaskProcessor.ts` — polls queued messages, calls
   `chatStore.startTask(...)` (which POSTs `/chat` and drains the SSE stream in
   the renderer), then writes status back with `proxyUpdateTriggerExecution`.

These three are mounted in `agent-ui/src/agent-embed/AgentEmbedPanel.tsx:144-146`
(and in the standalone `App.tsx`).

### 1.3 So the agent loop *does* run on the brain — but only on demand

`chatStore.startTask` builds the `Chat` body from **client** state and POSTs
`/chat`. `brain/app/controller/chat_controller.py` `start_chat_stream()` (`:432`)
runs the real agent (workforce or single-agent) and streams SSE back. The loop
lives server-side, but it is *driven and drained by the client's connection*.

**No client draining the stream ⇒ no run.** That is the whole bug.

---

## 2. What a server-side executor needs

Add a brain service that, on fire, builds a `Chat` and drives
`start_chat_stream` to completion itself, then writes the execution record. There
is precedent for constructing a `Chat` from scratch server-side:
`brain/app/router_layer/message_router.py:168-183` already does it with env
fallbacks (`api_key=payload.get("api_key") or env("OPENAI_API_KEY", "")`).

Inputs the client supplies today, and where the server would get them:

| `Chat` field | Today (client) | Server-side source |
|---|---|---|
| `email`, `user_id` | auth store | `UNDISCLOSED_LOCAL_EMAIL` (`chat_platform_controller.py:365`), `_DEFAULT_LOCAL_USER_ID` (`:118`) |
| `model_platform`/`model_type`/`api_key`/`api_url` | BYOK provider store | `~/.undisclosed/providers.json` (the `prefer: true` row), `chat_platform_controller.py:626-663`; env fallback like `message_router.py:180` |
| `project_id`, `space_id` | active project | already stored on the trigger record (`trigger_controller.py:735-736`) |
| `question` | composed message | `trigger["task_prompt"]` + event context (port `formatTriggeredTaskMessage`) |
| `installed_mcp` | connector gateway config | `~/.undisclosed/configs.json` (`chat_platform_controller.py:748+`) |
| `new_agents`, `session_mode` | worker list / project mode | **no server default today** — must pick (see §5) |
| browser | prepared per request | `_prepare_browser_for_request` is best-effort and returns `False` without raising (`chat_controller.py:118-209`), so a run can proceed browser-less |

Encouraging: the credentials a run needs are already persisted on the brain
(`providers.json`, `configs.json`, `~/.undisclosed/.env`), so the executor is not
blocked on secret hand-off.

---

## 3. Design

### 3.1 Options

- **A (recommended). Brain runs the agent in-process on fire.** Client hooks
  become observers/idempotent no-ops. One execution path, works with no panel.
- **B. Keep client execution, add a server fallback when no WS client is
  connected.** Shortest step, but two code paths that must stay in sync and a
  double-run hazard whenever a panel *is* open.
- **C. Skip the agent; post the result directly to Slack.** Not wanted: no
  reasoning, no tools, no other trigger types.

Go with **A**, treat **B** only as a temporary flag if we want to ship
incrementally.

### 3.2 Pieces

1. **`brain/app/service/trigger_executor.py` (new).**
   - `run_execution(execution, trigger)`: resolve model from
     `providers.json`; build `Chat` (see §2); drain the `start_chat_stream`
     generator; capture final text/tokens; write back
     `status/output_data/tokens_used/tools_executed` via the trigger store and
     `broadcast({"type": "execution_updated", ...})`.
   - Per-project serialization (mirror the client's per-project guard in
     `useBackgroundTaskProcessor`) plus a global concurrency cap.
   - Failure/retry: honor `max_retries` / `consecutive_failures` already on the
     trigger record.

2. **Wire the fire sites.** `dispatch_slack_event`, `_run_due_schedule_triggers`,
   `receive_webhook` should hand the execution to the executor instead of only
   broadcasting. Note these run on background threads; `broadcast()` already
   crosses threads via `run_coroutine_threadsafe`, so do the same for the run
   coroutine, and start any loop-bound machinery from the app's `_lifespan`
   (the `on_event("startup")` handler is dead — see the earlier finding — so do
   not put it there).

3. **Idempotency / single-owner (the critical bit).** When the server executes,
   the client hooks must not *also* run the same execution, or a Slack mention
   yields two replies. Options: have the executor claim the execution
   (`pending → running`) and make `useTriggerTaskExecutor` skip executions
   already claimed; or gate the client path behind a server capability flag.
   Decide before writing the executor.

4. **Project/run home.** The client is what currently creates/loads the project
   and scaffolding (`useTriggerTaskExecutor`, `loadProjectFromHistory`,
   `createProject`). The executor must ensure a runnable project exists for the
   trigger's `project_id`/`space_id` (or run with the id as-is and let
   `get_workspace_resolver()` scaffold). Verify `workspace_resolver` requirements
   before coding — it needs a valid project/space and writes a task snapshot.

5. **Slack reply.** Two ways: let the agent select `slack_toolkit` (enabled when
   `SLACK_BOT_TOKEN` is set) and post to the event's `channel_id`; or add a
   deterministic "post the final answer to `channel_id`" step after the run.
   The deterministic step is more reliable; the agent-tool path is more general.
   Pick one (see §7).

6. **Status/observability.** The UI's executions list is REST-backed; the
   executor writes the same records and broadcasts `execution_updated`, so any
   open panel reflects live status without owning the run.

---

## 4. The lifecycle caveat (read this before promising "app closed")

The brain is launched by the desktop app (`packages/undisclosed-agent/src/node/`
brain launcher; `scripts/brain.sh` in dev). **Quit the app and the brain stops** —
so the Socket Mode listener (and any executor) stops with it.

Therefore "server-side execution" here means *runs without the chat panel being
the executor*, not *runs with the app fully closed*. True app-closed operation
needs the brain as an always-on process (launchd/systemd/container) with its own
persistence — a separate, larger track. Phase 1–2 below deliver the former.

---

## 5. Risks / unknowns

- **Double execution** (client + server) → duplicate replies. Highest-priority
  correctness risk; solved by §3.2(3).
- **Model tool-calling.** A Slack reply depends on the model supporting tool
  calls and selecting the tool. Some BYOK models don't. Deterministic post
  removes this variable.
- **`new_agents` / `session_mode` defaults.** The client builds the worker list;
  the server has none. Defaulting to single-agent is the safe start, but it
  changes behavior vs. a workforce run — needs a product call.
- **Credentials on disk.** `providers.json` holds `api_key` in plaintext today;
  server-side runs keep keys resident (no change, but more frequent use).
- **Browser.** `_prepare_browser_for_request` won't raise, but a browser-needing
  task run headless adds latency and failure surface. Slack-reply tasks likely
  don't need one.
- **Concurrency/retries.** The current scheduler is a naive daemon thread
  (`_ensure_scheduler`, `:585`). A real queue + cap is new code, not a tweak.
- **Memory scaffolding.** `MemoryService.on_run_start` writes Space/Project/Run
  scaffolding keyed by the run context; needs a valid project/space or it
  degrades.

---

## 6. Suggested phasing

- **Phase 1 — prove the loop runs headless.** Executor service + wire
  `dispatch_slack_event` only + model resolution from `providers.json` + status
  writeback + the claim/idempotency fix. One Slack mention, panel closed, bot
  replies. This is the demo that retires the caveat.
- **Phase 2 — make it real.** Schedules + webhooks, concurrency cap, retries,
  `execution_updated` broadcast, connector/MCP wiring, browser policy.
- **Phase 3 — always-on.** Run the brain as a service so it survives app quit
  (separate track; needed only if "app fully closed" is the target).

---

## 7. Open questions (need answers before coding)

1. Replace the client hooks entirely (§3A), or keep them and stand down only
   when no WS client is attached (§3B, transitional)?
2. Slack reply: deterministic post of the final answer, or let the agent choose
   the tool?
3. Default `session_mode` and worker set for an automation run?
4. Definition of done: "app open, panel closed" (Phase 1–2) or "app fully
   closed" (needs Phase 3)?
