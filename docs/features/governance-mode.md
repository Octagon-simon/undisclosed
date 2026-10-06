# Governance Mode: How Commands Are Gated

_Last verified against source on 2026-10-06._

This document describes exactly how "governance mode" decides which agent
actions require a human approval prompt, and what those actions are. It is a
read-only description of current behavior; no behavior was changed.

---

## TL;DR (the important part)

**Governance gates at the TOOL level, not the command level.**

When governance is in **Ask** mode, the assembler wraps a fixed set of
*mutating tools*. For the terminal, it wraps the entire `shell_exec` tool. The
wrapper asks for approval **before it ever looks at the arguments**, so in Ask
mode **every** `shell_exec` call prompts, no matter what the command is:

- `ls -la` -> prompts
- `git status` -> prompts
- `rm -rf /` -> prompts

There is **no "is this command dangerous?" classifier** anywhere in our
governance layer today. The only place in the stack that reasons about
"dangerous commands" is CAMEL's `safe_mode` denylist, which *hard-blocks*
(rather than prompts for) a fixed list of commands. That layer is separate from
governance and is described in the last section.

So the feature you want ("only show the box when the command is actually
dangerous") is **not a config flag** we can flip. It requires teaching the
gate to inspect the tool call's arguments and decide per-call. See
["Where a danger check would go"](#where-a-danger-check-would-go).

---

## 1. The two modes

| Mode | Behavior |
| --- | --- |
| `auto` (default) | No gating. Tools run immediately. This is the shipped default ("ship dark"). |
| `ask` | The gated tools below require explicit human approval before they execute. |

The value is a per-session setting, not a build-time constant. Unknown or
misspelled values fall back to `auto` (fail-open on config typos, so a bad
config can never lock the agent out of its own tools).

- Type + coercion: `brain/app/agent/toolkit/governance_toolkit.py:52-71`
  (`GovernanceMode.coerce` maps `ask`/`always`/`manual`/`human` -> ASK,
  everything else -> AUTO).
- Default: `brain/app/agent/factory/toolkit_assembler.py:94`
  (`"governance": {"enabled": True, "mode": "auto"}`).

## 2. How the mode reaches the backend

The user sets it in the UI; it rides along on every chat request in
`toolkit_config`.

1. **UI state** (`agent-ui`)
   - Type: `agent-ui/src/store/authStore.ts:36` (`GovernanceMode = 'auto' | 'ask'`).
   - Default: `agent-ui/src/store/authStore.ts:264` (`governanceMode: 'auto'`).
   - Setter: `agent-ui/src/store/authStore.ts:402` (`setGovernanceMode`).
   - Toggle UI: `Settings > Privacy` at
     `agent-ui/src/pages/Setting/Privacy.tsx:49-50` and `:160-161`
     (`checked ? 'ask' : 'auto'`).
   - Also exposed in the editor title bar via the `...` menu:
     `packages/undisclosed-agent/src/browser/undisclosed-agent-contribution.ts:154-159`
     (commands `undisclosed-agent.governance-ask` / `-auto`).
   - A live badge shows the current mode:
     `agent-ui/src/components/CodeAgentWorkspace/RightAgentPanel.tsx:95`
     (`isAsk = governanceMode === 'ask'`) and the header chip at `:180-190`
     ("Approval required for risky actions" vs "Actions run automatically").

2. **Sent on each request**
   `agent-ui/src/store/chatStore.ts:2348-2352`:
   ```ts
   toolkit_config: {
     governance: { mode: governanceMode },
     memory: { enabled: memoryEnabled },
     thinking: { enabled: showThinking },
   },
   ```

3. **Backend model + merge**
   - Field: `brain/app/model/chat.py:102` (`toolkit_config: dict | None`).
   - Merged over defaults: `brain/app/agent/factory/toolkit_assembler.py:130-137`
     (`_merged_config`).
   - Resolved once per assembly:
     `brain/app/agent/factory/toolkit_assembler.py:158-162` (`_governance_mode`).

## 3. What gets gated (the exact list)

Gating happens in `assemble_single_agent_toolkits`
(`brain/app/agent/factory/toolkit_assembler.py:453+`). When
`governance_mode is GovernanceMode.ASK`, it wraps specific tool names via
`_gate_tool_if_named` (`:165-197`). The complete set:

| Toolkit | Gated tool name(s) | `field_name` (label in prompt) | Call site |
| --- | --- | --- | --- |
| File | `write_to_file` | `file_write` | `toolkit_assembler.py:496-503` |
| Terminal | `shell_exec` | `terminal` | `toolkit_assembler.py:674-681` |
| Git | `git_add`, `git_commit`, `git_create_branch`, `git_checkout`, `git_stash` | `git_write` | `toolkit_assembler.py:693-700` |
| Test Runner | `generate_tests`, `fix_failing_tests` | `test_generation` | `toolkit_assembler.py:712-719` |
| Diff | `apply_patch` | `file_write` | `toolkit_assembler.py:731-738` |

The Git and Test Runner name sets are declared in their toolkits:
`brain/app/agent/toolkit/git_toolkit.py:40-46` and
`brain/app/agent/toolkit/test_runner_toolkit.py:50`. The Diff set is at
`brain/app/agent/toolkit/diff_toolkit.py:41`.

**Not gated** (run freely in both modes): all read-only tools, plus
`web_deploy`, `browser`, `screenshot`, `skill`, `search`, `web_fetch`,
`code_query`/`code_search`, `memory`, `mcp`, `agent` (delegation), `todo`,
`human`, `project_context`, `planning_worktree`.

Note on the terminal: the model-facing tool is named **`shell_exec`**, even
though the class is `TerminalToolkit`. That is the only name in the target set
for the terminal, so wrapping it wraps every terminal invocation.

## 4. The gate mechanism (per-tool wrapper)

`_gate_tool_if_named` walks the toolkit's tools and, for each `FunctionTool`
whose name is in the target set, swaps it for a wrapped version produced by
`wrap_with_approval` (`brain/app/agent/toolkit/governance_toolkit.py:74-197`).

Key properties of the wrapper:

- It returns a **new** `FunctionTool` preserving the original's
  name/description/parameters, so the model's view of the tool is unchanged.
- On **every** call it: builds a short human-readable summary of the arguments
  (`_describe_call`, `:205-216`), then calls
  `ApprovalManager.request_approval(...)` and blocks until a decision lands.
- It resolves the per-session `ApprovalManager` through the task lock:
  `get_task_lock(project_id).approval_manager`. This is the same instance the
  SSE and HTTP layers use.
- **Fail-closed:** if there is no task lock or no `ApprovalManager`, the tool
  does **not** run; it returns a `[SYSTEM GOVERNANCE]: ... Refusing to run the
  mutating action.` string (`:113-136`).
- **Denied / timeout** -> it returns a
  `[SYSTEM GOVERNANCE]: the requested '<tool>' action was denied...` string
  instead of raising, so the model can replan (`:145-165`). Denied decisions
  are `DENIED_DECISIONS = {"denied", "timeout"}` (`:48-49`).
- Only on approval does it call the underlying tool
  (`tool.async_call(*args, **kwargs)`, `:167-177`).

There is a subtle but important detail documented in the file (`:179-192`): the
wrapper deletes `__wrapped__` so CAMEL reports the gated tool as **async**. If
it were reported sync, CAMEL would run it on a separate loop and *block* the SSE
event loop, so the approval prompt could not be flushed until the 120s timeout.

## 5. The approval lifecycle (ApprovalManager + SSE + HTTP + UI)

The per-session manager is `ApprovalManager`
(`brain/app/service/approval_manager.py:70`), stored on the task lock as
`approval_manager` (`brain/app/service/task.py:483-486`, created lazily on the
first solve loop).

Flow:

1. **Request** (`request_approval`, `approval_manager.py:87`)
   - Creates a pending entry keyed by a random `approval_id`, with an
     `asyncio.Future`.
   - Fires the `permission_requested` hook (fire-and-forget).
   - Pushes an `approval_request` event onto the SSE queue.
   - Waits on the future, bounded by `approval_timeout_s` (**default 120s**,
     `approval_manager.py:77`).
   - Timeout resolves as `"timeout"` (treated as deny) via `_on_timeout`.

2. **SSE payload**
   `brain/app/service/task.py:341-368`:
   - `approval_request`: `{ approval_id, tool_name, detail, agent_name }`
   - `approval_resolved`: `{ approval_id, decision, decided_by }`
     (`decision` in `approved` / `denied` / `timeout`).

3. **Human decision** (HTTP)
   `POST /chat/{id}/approval`
   (`brain/app/controller/chat_controller.py:896-934`) with
   `ApprovalDecision { approval_id, decision, decided_by }`
   (`brain/app/model/chat.py:235-239`). It calls `manager.resolve(...)`, which
   fires `permission_resolved`, pushes `approval_resolved`, and wakes the
   future. Unknown/already-settled ids are an idempotent no-op.

4. **Hooks**
   `brain/app/hooks/events.py:51-55` defines `permission_requested`,
   `permission_approved`, `permission_denied`, `permission_timeout`. These let
   external observers (e.g. beckon) resolve an approval out-of-band.

5. **UI**
   - SSE handler parks the pending request on the task:
     `agent-ui/src/store/chatStore.ts:4732-4746` sets `activeApproval`; the
     resolved event clears it at `:4748-4759`.
   - The prompt is `ApprovalRequestCard`
     (`agent-ui/src/components/ChatBox/MessageItem/ApprovalRequestCard.tsx`):
     a sticky overlay next to the "Stop Task" control, with **Approve** /
     **Deny** buttons, a `ShieldAlert` icon, and the tool name + a
     `friendlyApprovalDetail()` extraction of the meaningful argument (it pulls
     `command=...` out of the raw `shell_exec(...)` string so the user sees the
     command, not the signature).

## 6. CAMEL `safe_mode` (a different layer, hard-blocks instead of prompting)

Separate from governance, the terminal toolkit is constructed with
`safe_mode=True` (`brain/app/agent/factory/toolkit_assembler.py:663`). This is
CAMEL's own command-level security layer, in
`brain/.venv/.../camel/toolkits/terminal_toolkit/utils.py`. It does not prompt;
it **refuses the command** and returns an error string. It covers:

- A fixed **`DANGEROUS_COMMANDS`** denylist (`utils.py:62-112`): `sudo`, `su`,
  `reboot`, `shutdown`, `rm`, `chown`, `chgrp`, `mount`, `umount`, `dd`,
  `mkfs`, `fdisk`, `parted`, `fsck`, `mkswap`, `swapon/swapoff`, `service`,
  `systemctl`, `iptables`/`ip6tables`, `ifconfig`, `route`, `crontab`, `at`,
  `useradd`/`userdel`/`usermod`, `passwd`, `modprobe`/`rmmod`/`insmod`, etc.
- `cd`/`pushd` outside the working directory.
- Chained multiple `cd`/`pushd` with shell operators.
- Shell command substitution (backticks / `$(`).
- An optional `allowed_commands` **allowlist** mode (currently not set by the
  app; `allowed_commands=None`).

So today a dangerous command in the denylist is **blocked** by CAMEL, and in
Ask mode the user is *also* prompted first (governance runs before the
underlying tool, so the prompt appears, and if approved the command then still
hits the safe-mode block).

---

## Where a danger check would go

If the goal is "prompt only for dangerous commands", the decision has to move
from *assembly time* (which tool) to *call time* (which arguments). The natural
extension points:

- **Primary:** inside `wrap_with_approval`
  (`brain/app/agent/toolkit/governance_toolkit.py:74-197`). Before calling
  `manager.request_approval(...)`, it already has `name`, `args`, and
  `kwargs`. Add a classifier here: if the call is benign, run it directly and
  skip the prompt; if it's dangerous (or unrecognized), prompt.
  - For the terminal, the relevant argument is `command` on `shell_exec`
    (`args[0]` or `kwargs["command"]`).
  - Reuse CAMEL's `DANGEROUS_COMMANDS` list as one signal; add a read-only
    allowlist (e.g. `ls`, `cat`, `grep`, `find`, `git status/diff/log`) as
    another; treat anything unrecognized as "ask" (fail-closed for unknown).
- **Alternative / complementary:** don't wrap the whole `shell_exec` tool;
  instead wrap it with a wrapper that only prompts conditionally (same as
  above, just framed as "conditional gate" rather than "unconditional gate").

Things to decide when implementing:

- Default posture for unrecognized commands (recommend: ask).
- Whether `auto` mode should still hard-block CAMEL's `DANGEROUS_COMMANDS`
  (it currently does, via `safe_mode`).
- Whether the classifier lives in the brain (authoritative, shared) or the
  wrapper only (minimal change). Recommend the brain, so tests can cover it
  directly (see `brain/tests/app/agent/toolkit/test_governance_toolkit.py`).

## Source index (quick map)

- Mode + wrapper: `brain/app/agent/toolkit/governance_toolkit.py`
- Which tools get wrapped: `brain/app/agent/factory/toolkit_assembler.py:453-781`
- ApprovalManager: `brain/app/service/approval_manager.py`
- SSE payloads + task-lock field: `brain/app/service/task.py:341-368`, `:483-486`
- HTTP resolve endpoint: `brain/app/controller/chat_controller.py:896-934`
- Hooks taxonomy: `brain/app/hooks/events.py:51-55`
- Frontend toggle: `agent-ui/src/store/authStore.ts`, `agent-ui/src/pages/Setting/Privacy.tsx`
- Frontend request wiring: `agent-ui/src/store/chatStore.ts:2348-2352`, `:4732-4759`
- Approval prompt UI: `agent-ui/src/components/ChatBox/MessageItem/ApprovalRequestCard.tsx`
- CAMEL safe_mode: `brain/.venv/.../camel/toolkits/terminal_toolkit/utils.py`
- Existing tests: `brain/tests/app/agent/toolkit/test_governance_toolkit.py`,
  `brain/tests/app/service/test_approval_manager.py`
