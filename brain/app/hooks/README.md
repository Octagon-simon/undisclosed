# Lifecycle hooks

Beckon-style hooks for Eigent's backend, modeled on Claude Code's
`Notification` hook and Codex's `notify` config: when something happens
that a human might want to know about (a permission request, a finished
task), Eigent runs whatever external command you configured and hands it
the event as JSON on **stdin**. Fire-and-forget: hooks never block agent
execution, never raise into task code, and are silent no-ops when nothing
is configured.

## Events

| Event | Fired when |
|---|---|
| `task_started` | a single-agent turn begins executing |
| `task_end` | a turn completes successfully |
| `task_failed` | a turn raises before producing a result |
| `task_cancelled` | the user stops or skips the run |
| `human_input_requested` | the agent asks the user a question |
| `permission_requested` | an Ask-mode mutating action waits for approval |
| `permission_approved` / `permission_denied` | the user resolves the request |
| `permission_timeout` | the request times out (auto-deny) |
| `session_paused` / `session_resumed` | the user pauses/resumes |

Payload shape (flat JSON scalars only, compatible with beckon's
`eigent-hook` adapter):

```json
{"event": "permission_requested", "taskId": "...", "actionId": "...",
 "toolName": "TerminalToolkit.run_command", "category": "shell",
 "description": "npm test", "agentName": "single_agent",
 "timeoutSeconds": 120, "timestamp": 1756000000.0}
```

## Configuration

Two sources, combined additively (all matching commands run):

1. `EIGENT_HOOKS` — JSON object mapping event names (or `"*"`) to a command
   string or list of command strings:

   ```bash
   export EIGENT_HOOKS='{
     "permission_requested": ["node /path/beckoned-eigent-hook.js"],
     "*": "/usr/bin/logger -t eigent-hook"
   }'
   ```

2. `EIGENT_NOTIFY_COMMAND` — the original single command from the beckon
   patch. Still fires for every event unless explicitly suppressed.

An explicit empty list (`"task_end": []`) is the kill switch for an event:
it suppresses the wildcard and legacy command for that event only.
`EIGENT_HOOK_TIMEOUT_MS` overrides the per-command timeout (default 2000).

Unknown event names in `EIGENT_HOOKS` are ignored with a warning, so the
config tolerates forward/backward version skew.

### Beckon (macOS notifications)

```bash
export EIGENT_NOTIFY_COMMAND="node $HOME/.beckoned/opt/dist/bin/beckoned-eigent-hook.js"
# or, per-event routing:
export EIGENT_HOOKS='{"*": "node '$HOME'/.beckoned/opt/dist/bin/beckoned-eigent-hook.js"}'
```

Verify with `beckoned-test`, or fire one synthetic event through Python:

```python
import asyncio, os
os.environ["EIGENT_NOTIFY_COMMAND"] = "node ~/.beckoned/opt/dist/bin/beckoned-eigent-hook.js"
from app.hooks.dispatcher import fire_hook
from app.hooks.events import HookEvent
asyncio.run(fire_hook(HookEvent.task_end, taskId="demo"))
```

## Usage from backend code

```python
from app.hooks.emitters import emit_task_completed

_fire_hook(emit_task_completed(task_id=task_id))  # see single_agent_service
```

Emitters are coroutines; schedule them (never await inline on hot paths).
From worker threads without a loop, use
`app.hooks.dispatcher.emit_event_thread_safe`.

## Where events are wired today

- `app/service/single_agent_service.py` — task lifecycle + pause/resume
- `app/agent/toolkit/human_toolkit.py` — `human_input_requested`
- `app/utils/workforce.py` — `task_end` on workforce shutdown
- Permission events are emitted by the governance layer (ApprovalManager)
  as soon as an Ask-mode action is requested/resolved/timed out.
