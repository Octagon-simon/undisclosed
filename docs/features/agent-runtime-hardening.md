# Agent runtime hardening

A coding agent that runs unattended on your machine will hit the ugly paths:
stuck tools, restarts, duplicate turns, malformed model output. This doc records
each hard-won fix and *why* it exists, so nobody "simplifies" a guard back into a
bug.

---

## 1. The wedged brain / freeze (commit `736d82a`)

**Symptom.** The brain went deaf. `/health` and the editor's `/api` proxy hung,
and the desktop surfaced it as a 502 ("brain went dead, restart it"). It looked
like a crash but was not.

**Root cause.** The brain is a single uvicorn event loop. Synchronous tools
(`shell_exec`'s subprocess, git/file scans) were called **on** that loop, so a
blocking tool stalled every other request, including `/health`, for the whole
command.

**Fix.** Run sync tools with `asyncio.to_thread` in
`brain/app/agent/listen_chat_agent.py`. `to_thread` copies the current context, so
the `process_task` ContextVar still propagates (unlike `run_in_executor`). Related
fixes: a brain `/health` watchdog, a single-owner port guard, and editor-side
retry/reconnect for transient loopback failures.

## 2. Reload vs auto-restart (commits `d8ad89d`, `e1e1a1a`)

Two different mechanisms, easily confused:

- `UNDISCLOSED_BRAIN_RELOAD` = **watch mode for file edits**. Read in
  `brain/main.py::run_standalone`; when truthy, uvicorn runs with `reload=True`
  (WatchFiles). Saving any `brain/**.py` restarts the server. Never restarts on a
  crash, and is force-disabled when frozen (the reloader cannot run under
  PyInstaller).
- `UNDISCLOSED_BRAIN_AUTO_RESTART` = **respawn on failure**. Lives in
  `scripts/brain.sh` `start()`: if the server exits unexpectedly, the supervisor
  respawns it after 2s. Does nothing on file edits.

Both are documented in `.env.sample`. For the dev brain, keep `RELOAD=false`: the
agent session runs *inside* that worker, so a reload wipes the session. This exact
footgun (edits to `resolver.py` silently bouncing the brain) is why reload is off
by default and why `scripts/brain.sh` forces `UNDISCLOSED_BRAIN_RELOAD=0` (process
env outranks `.env`). See also `BrainLauncher.restartCount`, which is capped at
`MAX_RESTARTS=10` and is not reset, so after ~10 wakes it gives up respawning.

## 3. Deferred follow-ups (sent mid-turn)

**Symptom.** A follow-up sent while a turn was running was only injected into the
live agent's memory; if the current turn finished without addressing it, it was
never answered. It looked "skipped" until the user re-sent it.

**Fix.** Such follow-ups are now **queued** and, as soon as the agent is idle, run
as their own normal turn (confirmed + run_turn + end). Multiple queue and run in
order. The unreliable mid-run memory inject was removed because it risked the
current turn *and* the deferred turn both answering. This also let us drop the
blunt `max_iteration` cap (see [../systems/token-management.md](../systems/token-management.md)).

## 4. Keep only the final answer (commit `6595e15`)

**Symptom.** In a multi-step tool loop the delta stream yields the content of
*every* iteration: each tool call is preceded by a "Let me read X" preamble. The
final message (and what got persisted and re-fed to the model) was a pile of
narration.

**Fix.** `SegmentAccumulator` in `listen_chat_agent.py` resets its buffer at each
tool-call boundary (detected by the cumulative `info["tool_calls"]` count growing)
and keeps the last non-empty segment. It is used in both `_stream_chunks` and
`_astream_chunks`, mirrored by `_response_content` in `single_agent_service.py`.

## 5. Malformed tool-call arguments don't kill a turn

**Symptom.** CAMEL's `_handle_batch_response` does a bare
`json.loads(tool_call.function.arguments)`. When a model emits truncated/invalid
JSON (finish_reason=length, provider quirk), that raises and kills the whole turn.

**Fix.** Two-layer recovery in `ListenChatAgent`: the first pass raises
`_MalformedToolCallArgs` so the completion is re-requested once (the only safe
recovery for a truncated call); if it is still malformed, the raw payload is
logged and arguments are substituted with `{}` so the tool fails cleanly at
execution and the model can retry, preserving the 1:1 tool_call -> tool_result
contract.

## 6. Other guards

- **Single-agent activation echo suppressed**: the activation "message" only
  narrates workforce subtasks, so for the single agent it is blanked, otherwise the
  user's own prompt appeared as a bogus "thinking" line.
- **Model auth-error reload**: a retryable 401/expired-key error triggers a single
  model refresh via `model_reload_callback` instead of failing the turn.
- **Drop the agent after a cancelled turn** so the next follow-up rebuilds clean
  MCP/browser transports instead of reusing half-torn ones.
- **Brain stop targets the listen socket only**, polls for graceful shutdown
  before SIGKILL, and lets `restart` proceed if `stop` returns non-zero, so
  stopping the brain no longer kills the editor backend.
- **Turn-start acknowledgement** (`ddf3a66`): a one-time message so the user sees
  the agent received the turn.

## Where it lives

`brain/app/agent/listen_chat_agent.py`, `brain/app/service/single_agent_service.py`,
`brain/app/agent/factory/single_agent.py`, `scripts/brain.sh`,
`packages/undisclosed-agent/src/node/brain-launcher.ts`,
`apps/desktop/electron-entry.js`.
