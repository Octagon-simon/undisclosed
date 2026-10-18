# Governance Mode: How Commands Are Gated

_Last verified against source on 2026-10-18._

This document describes exactly how "governance mode" decides which agent
actions require a human approval prompt, and what those actions are. It is a
read-only description of current behavior; no behavior was changed.

---

## TL;DR (the important part)

Governance has two layers: the **approval gate** wraps a tool, and the
**command policy** (`brain/app/agent/toolkit/command_policy.py`) decides from
the live arguments whether that call needs a prompt.

| Tier | Examples | Auto | Ask |
| --- | --- | --- | --- |
| 0 read-only | `ls`, `git status`, `tsc --noEmit`, `npm test` | run | run |
| 1 workspace write | `npm install`, `mkdir`, `git add`, `git commit` | run | prompt |
| 2 destructive | `git push`, `git reset --hard`, `npm publish`, SQL drops | prompt | prompt |
| 3 hard block | `rm`, `sudo`, `shutdown`, `dd`, `mkfs`, `git rm` | reject | reject |

The terminal (`shell_exec`) is wrapped in **both** modes, so tier 2 prompts
even when the feature flag is off. Other mutating tools (`write_to_file`,
`git_add`, `apply_patch`, ...) are still wrapped only in Ask mode and are
tier 1. Tier 3 is rejected before the ApprovalManager is consulted, so
approval cannot override it.

---

## 1. The two modes

| Mode | Behavior |
| --- | --- |
| `auto` (default) | Tier 0 and 1 run immediately; tier 2 prompts; tier 3 is rejected. |
| `ask` | Tier 1 also prompts; tier 2 prompts; tier 3 is rejected. |

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
(`brain/app/agent/factory/toolkit_assembler.py:453+`). `_gate_tool_if_named`
(`:205-234`) wraps specific tool names. The terminal is wrapped in every mode;
the rest are wrapped when `governance_mode is GovernanceMode.ASK`. The
complete set:

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
- On **every** call it resolves the tier from the arguments (`_call_tier`).
  Tier 0 always runs directly, tier 1 runs directly in Auto, and tier 3 is
  rejected. Only when approval is needed does it build the summary
  (`_describe_call`) and call `ApprovalManager.request_approval(...)`, then
  block until a decision lands.
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

## 6. Command policy (tiers 0-3)

`brain/app/agent/toolkit/command_policy.py` classifies a shell command line
into four tiers. It is pure: no config, no I/O, tested directly.

| Tier | Examples | Auto | Ask |
| --- | --- | --- | --- |
| 0 read-only | `ls`, `cat`, `rg`, `git status`, `tsc --noEmit`, `npm test` | run | run |
| 1 workspace write | `npm install`, `mkdir`, `git add`, `git commit`, `echo > file` | run | prompt (flag) |
| 2 destructive | `git push`, `git reset --hard`, `git clean -fd`, `npm publish`, SQL drops | classified | classified |
| 3 hard block | `rm`, `sudo`, `shutdown`, `dd`, `mkfs`, `find -delete`, `git rm` | rejected | rejected |

`TerminalToolkit.shell_exec` also calls `assess_command(command)` and returns
a "blocked by the command policy" error for tier 3 before the Docker/local
split, before the venv activation prefix, and before CAMEL's `safe_mode`. The
approval wrapper applies the same tier check one layer up, so a blocked
command never reaches either path.

Splitting rules: the line is split on `&&`, `||`, `;`, `|`, `&`, newlines,
subshells, and backticks outside quotes. Each segment is classified and the
highest tier wins. Blocked binaries are also found inside `bash -c`, `eval`,
`xargs`, `find -exec`, and `$(...)`. Unknown commands are tier 1, not blocked,
so an unfamiliar command still runs. A quoted mention (`echo "rm -rf /"`) is
data, not a command, and is not blocked.

## 7. CAMEL `safe_mode` (a different layer, hard-blocks instead of prompting)

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

## Where the danger check goes

The classifier now exists (`command_policy.py`, section 6). The remaining work
is to consume it at *call time*, not assembly time, inside
`wrap_with_approval`:

- **Primary:** inside `wrap_with_approval`
  (`brain/app/agent/toolkit/governance_toolkit.py:74-197`). Before calling
  `manager.request_approval(...)`, it already has `name`, `args`, and
  `kwargs`. For `shell_exec`, run `assess_command` on the command string:
  tier 0 runs without a prompt, tier 1 prompts only in Ask mode (or when the
  task allowlist does not cover its scope), and tier 2 always prompts.
  - Reuse CAMEL's `DANGEROUS_COMMANDS` list as one signal; `command_policy`
    already covers the same binaries plus disk/database/deploy actions.
- **Also:** wrap the terminal in Auto mode, not only in Ask mode, so tier 2
  can prompt with the feature flag off. The wrapper needs the session's
  `GovernanceMode` passed in; it currently does not receive it.

Decisions already made:

- Unrecognized commands are tier 1 (run), not blocked. Blocking them would make
  the terminal unusable.
- Tier 3 is blocked in Auto too, and approval cannot override it.
- The classifier lives in the brain so both the gate and the terminal share it
  and tests hit it directly.

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
