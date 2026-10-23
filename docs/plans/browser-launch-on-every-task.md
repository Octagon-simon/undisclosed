# Chromium launches on every task, browser heuristics, and the fix

Status: implemented. Written originally against `5b181ae` (2026-10-23); the
line numbers below still describe the problem as found. Implementation notes
are in "Rollout" at the end.

## Summary

The agent does not start a browser because of schema loading or tool
discovery. It starts one because `start_chat` (and, separately, `improve`)
call `ensure_cdp_browser_endpoint` before the agent is built, on every turn
where the client did not already hand over a list of CDP browsers. After an
app relaunch that list is always empty, so the first turn of every session
launches Chromium. On a follow-up message the check is not even conditional:
the follow-up endpoint always calls it.

The single-agent path was already changed to defer the Browser Toolkit behind
`load_capability`. The eager prepare in the controller runs earlier and makes
that deferral pointless.

## Symptom and reproduction

1. Quit the app.
2. Relaunch it. The Electron CDP pool is in-memory, so it comes up empty.
3. Send any task that needs no web work (for example "summarise this file").
4. A Chromium window with the `cdp_brain_9222` profile opens.
5. Close the browser. Send another message. It opens again.

Observed on this machine at the time of writing: ten `Google Chrome for
Testing` processes from the Playwright cache, all launched with
`--remote-debugging-port=9222` and
`--user-data-dir=~/.undisclosed/browser_profiles/cdp_brain_9222`, started
between 2026-10-21 22:21 and 2026-10-23 07:25. The profile directory also
contains `cdp_brain_9223` through `cdp_brain_9232`, one per port the launcher
has walked through.

## The call chain

### Start of a chat

1. `agent-ui/src/store/chatStore.ts:2400-2414` calls
   `resolveCdpBrowsersForRequest()`. That helper
   (`chatStore.ts:357-394`) only asks the host to launch a browser when
   `shouldEnsureBrowserForRequest()` is true (`chatStore.ts:325-337`): a
   browser worker in the list, a URL in the message, or explicit browser
   intent. So the frontend is already gated correctly for single-agent turns.
2. After a relaunch, `get-cdp-browsers` returns `[]`, because the pool lives
   in the main process and was not persisted.
3. `brain/app/controller/chat_controller.py:489-494` sees
   `if not data.cdp_browsers:` and calls
   `_prepare_browser_for_request_with_timeout(request, data.browser_port)`.
   That condition is true for every first turn after a relaunch, and for every
   turn where the user's message had no browser intent.
4. `_prepare_browser_for_request` (`chat_controller.py:118-177`):
   - reuses a manually connected endpoint if one is stored on the request or
     in `UNDISCLOSED_CDP_URL` and it is reachable;
   - returns early for remote-cluster hands;
   - otherwise calls `ensure_cdp_browser_endpoint(port)` in a thread.
5. `ensure_cdp_browser_endpoint` (`brain/app/utils/browser_launcher.py:417-447`)
   walks `[preferred_port] + range(9223, 9300)`. For each port it checks
   `_is_cdp_available`, skips a port that is in use but not a managed CDP
   browser, and otherwise calls `ensure_cdp_browser_available`, which runs
   `_launch_browser` (`browser_launcher.py:316-348`) with
   `--remote-debugging-port=<port>`,
   `--user-data-dir=~/.undisclosed/browser_profiles/cdp_brain_<port>`
   and `start_new_session=True`.
6. The launch is then detached. `_launch_browser` returns a `Popen`, nothing
   stores the handle, and nothing ever terminates it.

### Follow-up messages

`chat_controller.py:616` calls `_prepare_browser_for_request_with_timeout`
unconditionally. `SupplementChat` (`brain/app/model/chat.py:219-233`) has no
`cdp_browsers` field at all, so there is no reuse list to check even if the
client still had one. Every follow-up repeats the launch check, and if the
user closed the browser in between, it relaunches.

### Why the port walks

`_is_cdp_available` is not just a socket check. It fetches `/json/version`
and then `_supports_browser_context_management` opens a browser-level
WebSocket to send `Browser.setDownloadBehavior`
(`browser_launcher.py:143-179`). A stale,
busy, or half-dead Chromium fails that probe (2s timeouts). Once it fails,
`ensure_cdp_browser_endpoint` sees the port is in use and permanently skips
it, moving to 9223, 9224, and so on. Ten orphaned Chromium processes holding
the same `cdp_brain_9222` profile is consistent with repeated launches that
never cleaned up, followed by a walk up the port range. That part is
inference from the observed state, not something a log line proves.

### The asymmetric timeout

`BROWSER_PREPARE_TIMEOUT_SECONDS` defaults to 8s
(`chat_controller.py:180-208`) while `ensure_cdp_browser_available` polls for
up to 10s (`browser_launcher.py:402-414`). `asyncio.wait_for` cancels the
awaiting coroutine, but `asyncio.to_thread` cannot cancel the thread. So a
launch can time out for the request and still complete afterwards: the task
starts, and a browser window opens seconds later that the run never uses.

### Why the toolkits are not to blame

- Single-agent assembly already defers the browser:
  `brain/app/agent/factory/toolkit_assembler.py:781-795` registers
  `_build_single_agent_browser` as a deferred capability when
  `_lazy_single_agent_extras()` is true (`toolkit_assembler.py:274-287`,
  requires tool-RAG, opt out with
  `UNDISCLOSED_SINGLE_AGENT_LAZY_BROWSER=0`). Chromium is only touched when
  the agent calls `load_capability("Browser Toolkit")`, and that path does
  call `ensure_cdp_browser_endpoint` (`toolkit_assembler.py:408-422`).
- The workforce path does not launch, but it also does not ensure: when there
  is no `cdp_browsers`, `brain/app/agent/factory/browser.py:274-294` points
  the toolkit at `http://localhost:9222` and assumes something is listening.
  A workforce build always constructs this agent
  (`brain/app/service/chat_service.py:2886-2896`), so removing the eager
  prepare without touching this path turns browser tasks in workforce mode
  into connection failures rather than launches.
- The actual connect is lazy and happens per tool call in
  `HybridBrowserToolkit._ensure_ws_wrapper`
  (`brain/app/agent/toolkit/hybrid_browser_toolkit.py:724+`), which logs
  `[PROJECT BROWSER] Connecting to browser via CDP at ...` and pulls from the
  WebSocket connection pool. That is the natural place for an on-demand
  launch.

### Dead state

`request.state.browser_available` is written in six places
(`chat_controller.py:135,143,156,164,174,205`) and read nowhere. Only
`browser_port` and `cdp_url` are consumed, by `_build_run_context`
(`chat_controller.py:211-240`) and by the follow-up context update
(`chat_controller.py:694-699`). `RunContext` turns `cdp_url` into
`UNDISCLOSED_CDP_URL` for downstream code
(`brain/app/run_context/context.py:40-58`), which is how the toolkit ends up
configured. So removing the prepare loses no readable state; it simply leaves
`cdp_url` as `None` unless a browser was actually reused.

## What is not the cause

Schema loading and tool discovery are string work: the tool definitions are
assembled and serialised into the prompt and sent to the model. They do not
spawn processes. The launch happens before `RunContext` is built and before
any agent exists. The token cost of carrying schemas is a separate and real
issue, but fixing it would not stop the browser.

## Proposed change

Goal: a browser starts only when a browser tool is about to run.

1. In `start_chat`, replace the eager prepare with a reuse-only check.
   Keep the "manually connected endpoint" and remote-hands branches, drop
   the `ensure_cdp_browser_endpoint` call. Rename the helper to something
   like `_reuse_browser_for_request` so the name stops implying a launch.
2. In `improve`, do the same. It should reuse the endpoint recorded on the
   task's `RunContext` if it is still reachable, and otherwise leave
   `cdp_url` alone.
3. Add the on-demand launch at the connect point. In
   `HybridBrowserToolkit._ensure_ws_wrapper`, when there is no pooled
   connection, the endpoint host is local, and the endpoint is not reachable,
   call `await asyncio.to_thread(ensure_cdp_browser_endpoint, port)`, write
   the returned endpoint back into `_ws_config` (`cdpUrl`), and then connect.
   Keep a per-toolkit `_launch_attempted` flag so a broken environment cannot
   trigger a launch storm, and leave remote/non-local endpoints untouched.
4. Alternative, smaller diff: call `ensure_cdp_browser_endpoint` in
   `factory/browser.py:274-294` when `use_browser` and nothing provided an
   endpoint. This fixes workforce, but since the browser agent is always
   built, it still launches for every workforce task. It should be the
   fallback, not the default.
5. Keep an escape hatch: the "Keep a browser warm" setting (Settings >
   General, persisted in the auth store, sent as `keep_browser_warm` on the
   chat and follow-up requests) restores today's eager behaviour for anyone
   who depends on a browser being ready at task start. It defaults to off.
   `UNDISCLOSED_BRAIN_LAUNCH_BROWSER=0` keeps its current meaning (never
   launch, use whatever is already there); it now also disables the on-demand
   launch, so it stays a diagnostic flag.
6. Optional, separate concern: reap what we launch. Either track the `Popen`
   per port and terminate on shutdown, or launch with
   `--user-data-dir` plus a marker and clean up orphans on startup. Without
   this, profiles and processes will keep accumulating.

## Behaviour after the change

- Reasoning-only single-agent turn, no URL: no browser. Nothing calls
  `ensure_cdp_browser_endpoint`.
- Single-agent turn with a URL: the frontend still ensures a browser
  (`shouldEnsureBrowserForRequest` is true) and sends `cdp_browsers`, so the
  assembler reuses that port. No duplicate launch.
- Single-agent turn where the agent decides mid-run to use the web: the
  toolkit's first connect launches, and the capability load already goes
  through `_build_single_agent_browser`, which also ensures.
- Workforce task that never touches the web: no browser.
- Workforce task that does: the first browser tool call launches.
- Web mode with no Electron: same as above; the first browser tool call pays
  the launch, up to 10s, instead of every task paying it up front.

## Risks and trade-offs

- First browser action is slower by up to 10s of launch time. That is the
  trade for not launching on every turn.
- `_ensure_ws_wrapper` runs on each tool call. The launch check must be inside
  the "no pooled connection" branch and guarded by the attempt flag, or every
  call would pay a `/json/version` probe.
- Two processes could race to launch on the same port (for example two
  parallel workers). `ensure_cdp_browser_endpoint` already tolerates a
  non-managed port by moving on, and `_get_browser_bringup_lock` exists for
  the shared-tab path; use it or an equivalent lock around the launch.
- If the configured `cdp_url` points at a port the user closed, the toolkit
  must update its config to the newly launched endpoint, not keep retrying
  the dead one.
- `UNDISCLOSED_CDP_URL` is process-level via `apply_run_env_for_third_party`,
  so a value prepared for one run can leak into a later one. Reuse-only in the
  controller makes this less likely, but the toolkit should still verify
  reachability before trusting it.
- Removing the prepare removes the only place that set
  `request.state.browser_available`. Since nothing reads it, delete the field
  rather than leave it dead.

## Test plan

Hermetic, no real browser:

- `_reuse_browser_for_request` returns `False` and never calls the launcher
  when no endpoint is stored (patch `ensure_cdp_browser_endpoint` and assert
  it is not called).
- Reuses a reachable stored endpoint and fills `cdp_url`/`browser_port`.
- Drops a stored endpoint that fails the availability probe.
- `improve` does not launch when the task's `RunContext.cdp_url` is dead.
- `_ensure_ws_wrapper` calls the launcher exactly once on a dead local
  endpoint, updates `cdpUrl`, and does not call it again after a failure.
- `_ensure_ws_wrapper` never launches for a non-local endpoint or when
  `UNDISCLOSED_BRAIN_LAUNCH_BROWSER=0`.
- Capability deferral regression: assembling a single agent with no browser
  capability loaded does not call the launcher.

Manual, on a relaunched app:

- Non-web task: no Chromium process appears (`ps` check before/after).
- Web task: exactly one browser, started on first browser action.
- Follow-up after closing the browser on a non-web task: no relaunch.
- Follow-up on a web task: relaunch on the next browser action, not at the
  HTTP request.

## Rollout

Shipped without an env flag. The behaviour is a user setting instead:

- `agent-ui` auth store: `keepBrowserWarm` (default `false`), exposed as
  "Keep a browser warm" under Settings > General. It is persisted with the
  other app settings and sent on both `/chat` and `/chat/{id}`.
- `brain/app/model/chat.py`: `keep_browser_warm` on `Chat` and
  `SupplementChat`.
- `brain/app/controller/chat_controller.py`: `_resolve_browser_for_turn`
  dispatches to `_reuse_browser_for_request` (default, no launch) or the old
  `_prepare_browser_for_request_with_timeout` (keep warm). Both `start_chat`
  and `improve` go through it.
- `brain/app/agent/toolkit/hybrid_browser_toolkit.py`: `_ensure_ws_wrapper`
  calls `_ensure_reachable_cdp_endpoint` on the first connect, which launches
  once through `launch_local_cdp_browser` when the endpoint is local and dead.
- `brain/app/utils/browser_launcher.py`: `launch_local_cdp_browser` refuses
  remote endpoints and honours `UNDISCLOSED_BRAIN_LAUNCH_BROWSER=0`.

`request.state.browser_available` was removed; nothing read it.

## Open questions for review

- Should the on-demand launch live in `_ensure_ws_wrapper` (covers every
  caller, one place to reason about) or in `factory/browser.py` (earlier,
  simpler, but launches for every workforce task)? I prefer the former, with
  the factory as a fallback.
- Should a browser launched for a task be closed when the task ends? Today it
  is left running, which is convenient for a follow-up and is also how ten
  copies accumulated.
- Do we want a user-visible setting ("keep a browser warm") instead of an env
  flag, given both choices are defensible? Decided: yes. It is a UI toggle,
  not an env flag.
