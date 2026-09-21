# Hooks and notifications

**Problem.** You want to know when the agent needs you (a permission prompt, a
finished task) or wire the agent into your own automation, without the agent
depending on a specific desktop-notification system.

**Solution.** Lifecycle hooks: when something happens worth knowing about, the
brain runs whatever external command you configured and hands it the event as
JSON on stdin. Fire-and-forget.

**Module:** `brain/app/hooks/` (its own `README.md` is the full reference).

---

## Events

| Event | Fired when |
| --- | --- |
| `task_started` | a single-agent turn begins executing |
| `task_end` | a turn completes successfully |
| `task_failed` | a turn raises before producing a result |
| `task_cancelled` | the user stops or skips the run |
| `human_input_requested` | the agent asks the user a question |
| `permission_requested` | an Ask-mode mutating action waits for approval |
| `permission_approved` / `permission_denied` | the user resolves the request |
| `permission_timeout` | the request times out (auto-deny) |
| `session_paused` / `session_resumed` | the user pauses/resumes |

Payloads are flat JSON scalars (compatible with beckon's `eigent-hook` adapter),
for example:

```json
{"event": "permission_requested", "taskId": "...", "actionId": "...",
 "toolName": "TerminalToolkit.run_command", "category": "shell",
 "description": "npm test", "agentName": "single_agent", "timestamp": 1756000000.0}
```

## Design guarantees

- **Fire-and-forget**: hooks never block agent execution and never raise into task
  code. They are silent no-ops when nothing is configured.
- **Additive config**: `UNDISCLOSED_HOOKS` (a JSON object mapping event names or
  `"*"` to command strings) and the legacy `UNDISCLOSED_NOTIFY_COMMAND` both run;
  all matching commands fire.
- **Kill switch**: an explicit empty list (`"task_end": []`) suppresses the
  wildcard and legacy command for that event only.
- **Tolerant of version skew**: unknown event names are ignored with a warning.
- `UNDISCLOSED_HOOK_TIMEOUT_MS` overrides the per-command timeout (default 2000).

## Configuration

```bash
export UNDISCLOSED_HOOKS='{
  "permission_requested": ["node /path/beckoned-eigent-hook.js"],
  "*": "/usr/bin/logger -t eigent-hook"
}'
```

For macOS desktop notifications via Beckon:

```bash
export UNDISCLOSED_NOTIFY_COMMAND="node $HOME/.beckoned/opt/dist/bin/beckoned-eigent-hook.js"
```

## Where events are wired

- `brain/app/service/single_agent_service.py` (task lifecycle + pause/resume)
- `brain/app/agent/toolkit/human_toolkit.py` (`human_input_requested`)
- `brain/app/utils/workforce.py` (`task_end` on workforce shutdown)
- governance / `ApprovalManager` (permission events)

Emitters are coroutines; schedule them, never await inline on hot paths. From a
worker thread without a loop, use
`app.hooks.dispatcher.emit_event_thread_safe`.

## Key commits

The hooks layer landed with the acknowledgement/notification work around
`ddf3a66` and the surrounding agent-lifecycle commits; the authoritative
documentation is `brain/app/hooks/README.md`.
