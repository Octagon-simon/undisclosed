# Terminal freeze + governance v2

_Plan only. No behavior changed yet. Verified against source and `.brain.log` on 2026-10-18._

## 0. Status on 2026-10-18

**Terminal fixes 1-5 are implemented and tested; governance v2 is still design-only.**

- `brain/app/agent/toolkit/terminal_toolkit.py` now runs local commands against a
  per-session log file instead of a pipe (`start_new_session=True`, `wait(timeout)`,
  file-backed output), with a 10s default blocking budget.
- `brain/app/agent/toolkit/shell_sessions.py` is a project-scoped registry. It
  stores the process-group id, kills the whole group (SIGTERM then SIGKILL), and
  makes a session started in turn N visible to turn N+1.
- `shell_exec`, `shell_view`, and `shell_kill_process` are overridden for the
  local backend; Docker still uses CAMEL's path.
- `<shell_safety>` is in both `DEVELOPER_SYS_PROMPT` and `SINGLE_AGENT_SYS_PROMPT`,
  and "Automate Confirmation" is gone from `<terminal_tips>`.
- Tests: `brain/tests/app/agent/toolkit/test_terminal_process_control.py` (10).
  Full toolkit suite: 159 passed.

**Command policy (shipped 2026-10-18, ungated).**
`brain/app/agent/toolkit/command_policy.py` classifies a command into tier 0
(read), tier 1 (workspace write), tier 2 (destructive), or tier 3 (hard
block). `TerminalToolkit.shell_exec` enforces **tier 3 only**: `rm`, `sudo`,
`shutdown`, `dd`, `mkfs`, `find -delete`, `git rm`, and the Windows delete
commands are rejected before the Docker/local split, before the venv
activation prefix, and before CAMEL's `safe_mode`. Approval cannot override
the rejection. Tiers 0-2 are classified and returned in `CommandAssessment`
but the approval gate does not read them yet.

Tests: `brain/tests/app/agent/toolkit/test_command_policy.py` (88 cases) plus
three terminal cases (blocked before spawn, read-only runs, write runs).

**Tiered gate (shipped 2026-10-18).** `wrap_with_approval` resolves the tier at
call time: tier 0 runs in every mode, tier 1 prompts only in Ask mode, tier 2
prompts in every mode, tier 3 is refused before the ApprovalManager is
consulted. The terminal is now wrapped in both modes; other mutating tools stay
wrapped in Ask mode only and map to tier 1 (`file_write`, `git_write`,
`test_generation`) or tier 2 (`github_write`, `mongo_write`).
`test_governance_toolkit.py` is 29 cases. Toolsuite: 170 passed. `ruff` clean.

**Session allowlist (shipped 2026-10-18).** `ApprovalScope` lives in
`brain/app/model/enums.py` and is re-exported as `CommandScope` from
`command_policy.py`. `assess_command` now carries the scopes a command touches,
and the gate checks the task allowlist before prompting:

- Reads are allowed by default for every task, so tier 0 never prompts unless
  the user unchecks **File reads**.
- Tier 1 runs are skipped when every scope they touch is in the task allowlist
  (File reads, File writes, Builds & tests, Dependency installs, Git add &
  commit).
- Tier 2 and tier 3 are never suppressed.
- `resolve(..., allow_scopes=[...])` replaces the task's scope set, so
  unchecking a scope takes effect immediately.
- Scopes are stored on the TaskLock under `current_task_id`, so the next task
  starts fresh.

The SSE payloads now carry `tier`, `tier_label`, `scopes`, `description`,
`working_directory`, and `allowed_scopes`; the resolved payload carries
`scopes` and `expired`. The approval window is five minutes. GitHub, MongoDB,
and git writes are wrapped in AUTO too (`git_push` is tier 2).

The live approval card consumes those fields: tier chip, description, working
directory, and the scope row, and the POST sends `allow_scopes`.

**Still open:** developer/workforce parity (`developer.py` and the other worker
factories still build an ungated `TerminalToolkit`), and the persisted
"Expired" card state with Retry. The manager marks the payload `expired`, but
the store still clears the card and shows the timeout outcome.

### Design decisions from the review

1. The one-line explanation sits directly under **Approval needed**; the old
   "Shell command · developer agent" subtitle is removed.
2. The tier chip stays in the header: Destructive, Writes files, Read only.
3. The command block is full-width, scrollable, and never truncated.
4. The working directory sits under the command, not beside the description.
5. **File writes are tier 1 (workspace write), not tier 2.** In Ask mode the first
   write prompts; the task allowlist suppresses the rest of the writes in that
   task. In Auto mode a write runs, as it does today.
6. Suppression is scope-based, not per tool. The row shows **File reads**,
   **File writes**, **Builds & tests**, **Dependency installs**, and
   **Git add & commit**. Multiple scopes can be selected, and they are stored on
   the TaskLock, never globally.
7. **File reads are selected by default.** They are tier 0, so a fresh task
   never prompts for them. Unchecking **File reads** deliberately turns read
   approval back on for the rest of the task; that is the privacy switch. Tier 2
   destructive calls and tier 3 blocks never offer suppression.

Default selection for a fresh task is `['reads']`. When a tier 1 action prompts,
its own scope is pre-selected in the card, so approving with the row as-is
suppresses that category next time.

---

## 1. Why the terminal "freezes"

There are four separate causes. Three are real bugs; one was already fixed and should not be re-broken.

### 1.1 Blocking calls wait on a pipe that background children keep open

`brain/app/agent/toolkit/terminal_toolkit.py:352-395` overrides `shell_exec` but only delegates to CAMEL with `timeout` defaulting to `20.0`.

CAMEL's blocking path (`brain/.venv/.../camel/toolkits/terminal_toolkit/terminal_toolkit.py:741-816`):

```python
proc = subprocess.Popen(command, stdout=PIPE, stderr=STDOUT, stdin=PIPE, shell=True, ...)
stdout, _ = proc.communicate(timeout=timeout)   # line 764
```

`communicate()` reads until **EOF on the pipe**, not until the direct child exits. A command like

```bash
python -m http.server 8765 &
```

exits the `sh -c` parent immediately, but the Python child inherited the same stdout fd. EOF never arrives while the server runs, so the call sits there until `timeout` expires. Nothing is technically hung, but the turn shows one spinner for the entire timeout.

Observed: `.brain.log.prev:2498`, a repo-wide grep with `timeout=40` returned after exactly 40s with "Command did not complete within 40 seconds". The model chooses its own timeout (20, 40, 180 all appear in the logs), so this is 20 to 180 seconds of apparent freeze per call.

### 1.2 The timeout path leaves the command running and lies about the session

On `TimeoutExpired`, CAMEL does not kill the process. It registers it as a session and returns a "continues in background" message (`:766-816`). The session dict is created with `"running": True` and a reader thread is started, but the process was never detached from the turn. The next `shell_view` can block on the same pipe.

### 1.3 `shell_kill_process` kills the shell, not the tree

`terminal_toolkit.py:1191-1195`:

```python
session["process"].terminate()
time.sleep(0.5)
if session["process"].poll() is None:
    session["process"].kill()
```

`Popen` is created with `shell=True` and no `start_new_session=True`, so the process is `/bin/sh -c "<command>"`. Killing it leaves the grandchildren (a dev server, a watcher, `python -m http.server`) alive, still holding port 8765 and still holding the inherited stdout pipe. That is why killing a preview server "works" but the port stays busy and the next pipe read still hangs.

Observed: `.brain.log.prev:1940-1954`, kill issued at 21:34:33.410, returned "terminated" at 21:34:38.605. That path should take 0.5s; the extra ~4.7s is the engine waiting on the orphaned reader.

### 1.4 Sessions do not survive a turn

`self.shell_sessions` is per `TerminalToolkit` instance, and a new toolkit is constructed for each task/turn (`brain/app/agent/factory/toolkit_assembler.py:774-778`). A server started in turn N is invisible in turn N+1.

Observed: `.brain.log:2714`, `shell_kill_process(id='site-server')` returned "No active session found with ID 'site-server'" while the server was still answering on port 8765 from a different task. The agent then reports the kill failed, the user sees a stuck port, and the next server start fails with "address already in use".

### 1.5 The freeze that is already fixed (do not regress)

`brain/app/agent/toolkit/governance_toolkit.py:179-192`: `@wraps` was copying `__wrapped__` onto the async gate, so CAMEL classified the gated tool as synchronous. It then ran the coroutine on a separate loop with `run_coroutine_threadsafe(...).result()`, which froze the SSE loop for the whole 120s approval wait. Deleting `__wrapped__` fixed it. Any change to the wrapper must keep that line.

---

## 2. Fix plan for the terminal

Ordered by user-visible impact. All changes live in `brain/app/agent/toolkit/terminal_toolkit.py` unless noted.

**Fix 1: stop using the pipe as the completion signal.**
Create the process with `start_new_session=True` and redirect stdout/stderr to a per-session log file, not a `PIPE`. Wait with `proc.wait(timeout=...)`, which is unaffected by grandchildren holding an fd. Return the tail of the file. This alone removes the 20 to 180 second stalls and makes `block=True` bounded by wall clock, not by fd lifetime.

**Fix 2: make the blocking budget short and explicit.**
Cap the override's default at 10 seconds. If a command has not finished, return:

```
Command still running after 10s. Session '<id>'.
Read with shell_view('<id>'), stop with shell_kill_process('<id>').
Last output:
<tail>
```

No "continues in background" unless it is actually detached and visible.

**Fix 3: kill the process group.**
`os.killpg(os.getpgid(pid), SIGTERM)`, wait up to 2s, then `SIGKILL`. Return immediately; never join a reader that can block on an inherited fd. Verify the port is free when the command included one, and say so in the result.

**Fix 4: one registry per project, not per toolkit.**
Move `shell_sessions` to a module-level dict keyed by project id, or persist a small JSON at `~/.undisclosed/shells/<project_id>.json` with `{id, pid, pgid, command, started_at, log_file}`. Back `shell_kill_process` with that registry so a later turn can kill an earlier turn's server. If the session is unknown but the pid is alive, kill by pid. This makes "kill the preview server" work across turns.

**Fix 5: prompt guidance (see section 3).** The code cannot know that `npm run dev` is a server. The model must use `block=False` for it. Today the prompt actively encourages the opposite.

**Tests:**
- unit: blocking `sh -c 'sleep 30 &'` returns in under 12s and leaves a readable session
- unit: `kill` on a backgrounded child frees the port (spawn `python -m http.server 0`, read the port, kill, assert closed)
- unit: a session registered in toolkit A is visible to toolkit B for the same project
- regression: gated tool remains async (`is_async` is True after wrapping)

---

## 3. System prompt rules

Two prompts need this: `DEVELOPER_SYS_PROMPT` (`brain/app/agent/prompt.py:629`) and `SINGLE_AGENT_SYS_PROMPT` (`:843`). The developer prompt's current `<terminal_tips>` (`:802-834`) says "Be Creative: use the terminal boldly", "Automate Confirmation: use `-y` or `-f`", and tells the agent to stop processes with `shell_kill_process` but never mentions `block=False`, timeouts, or backgrounding. That section is why workers start servers in blocking mode.

Add a new section, and remove the "Automate Confirmation" line:

```text
<shell_safety>
- Deletion is disabled. `rm` is hard-blocked by the terminal and the command is
  rejected before it runs. Never attempt deletion with `rm`, `rmdir`, `unlink`,
  `find -delete`, or `git clean`. If removal is genuinely required, say so and
  let the user do it.
- Never run a command that rewrites the user's workspace beyond the task you were
  given. This includes `git push --force`, `git reset --hard`, `git clean -fd`,
  `git checkout -- .`, `git rebase`, `git branch -D`, `git stash drop`, database
  drops or updates, and deploys.
- Do not ask the user for permission before a shell command. The runtime shows an
  approval prompt with the exact command when approval is on. Asking as well
  produces two prompts for one action.
- If the runtime rejects a command, do not retry it or rephrase it to get around
  the rejection. Report what was blocked.
- Read-only verification is not dangerous and needs no approval: `ls`, `cat`,
  `rg`, `grep`, `find` (without `-delete`/`-exec rm`), `git status`, `git diff`,
  `git log`, `tsc --noEmit`, `eslint`, and the project's test runner.
- Commands that may run longer than 10 seconds must use `block=False` and be read
  with `shell_view`. Never start a server or watcher with `block=True`.
- Stop background work with `shell_kill_process(id="...")` in the same turn that
  started it, and never assume a session exists in a later turn.
</shell_safety>
```

That answers "any prompt on my system to know what to use": yes for code navigation (`<tool_usage>` tells the single agent to prefer tree-sitter tools over shell), but no for the terminal. The developer prompt has neither rule, so workers default to shell for everything.

---

## 4. Governance mode: what is actually there

Everything below exists today and is wired end to end:

> **Status (2026-10-18): shipped and on by default.** The feature flag is gone.
> New and existing sessions start in `ask`; `auto` is an explicit opt-in in the
> panel menu or Settings > Privacy. The "flagged off" lines below describe the
> pre-ship state that motivated this plan.

| Piece | Location |
| --- | --- |
| Mode enum + gate wrapper | `brain/app/agent/toolkit/governance_toolkit.py` |
| Which tools get gated | `brain/app/agent/factory/toolkit_assembler.py:524-808` |
| Approval wait, 120s timeout | `brain/app/service/approval_manager.py:77` |
| SSE request/resolved | `brain/app/service/task.py`, `chat_controller.py:964` |
| Store state | `agent-ui/src/store/chatStore.ts:396`, `:5079` |
| Prompt card above composer | `agent-ui/src/components/ChatBox/MessageItem/ApprovalRequestCard.tsx` |
| Outcome card | `.../ApprovalOutcomeCard.tsx` |
| Default mode | `ask` (`agent-ui/src/store/authStore.ts`); `auto` is opt-in |

So "we have not built it properly" is accurate, but the gap is not the plumbing. It is four things:

**4.1 The gate is tool-level, not command-level.** `wrap_with_approval` asks before it looks at the arguments. In Ask mode `ls -la` prompts exactly like `git push --force`. That is why the mode is unusable in practice and why it is now flagged off.

**4.2 Wrong scope.** Only the single agent's `shell_exec` is gated (`toolkit_assembler.py:781-788`). `developer.py:178-190` builds `TerminalToolkit` directly with no gate, so workforce workers and triggers can run the same destructive commands with no prompt. The README claims the gate covers terminal, file_write, git_write, github_write, mongo_write. That is true for the single agent only.

**4.3 `rm` being blocked conflicts with "approve it".** CAMEL's `safe_mode` rejects any command containing `rm` (`utils.py:215-219`). In Ask mode the user is prompted first, approves, and the tool then rejects the command anyway. Approval that cannot change the outcome is worse than no approval.

**4.4 `apply_patch` is a second deletion path.** A unified diff with `+++ /dev/null` deletes a file, and `apply_patch` is only gated in Ask mode (`diff_toolkit.py:41`). In Auto mode, "rm is disabled" is not a deletion guarantee. Decide whether that matters; if it does, gate `apply_patch` on the same tier as destructive shell.

---

## 5. Governance v2 design

### 5.1 Classify per call, in the brain

Extend `wrap_with_approval` so the decision happens at call time with the actual arguments. Put the classifier in a new `brain/app/agent/toolkit/command_policy.py` so both the gate and the terminal can import it and tests can hit it directly.

Tiers:

| Tier | Examples | Auto mode | Ask mode |
| --- | --- | --- | --- |
| 0 read-only | `ls`, `cat`, `rg`, `git status`, `git diff`, `tsc`, `eslint`, tests | run | run, no prompt |
| 1 workspace write | `npm install`, `mkdir`, `git add`, `git commit`, test file creation | run | prompt once, offer "allow for this task" |
| 2 destructive | `git push --force`, `git reset --hard`, `git clean -fd`, `git rebase`, `DROP TABLE`, deploy | prompt | prompt |
| 3 hard block | `rm`, `sudo`, `shutdown`, `mkfs`, `dd`, disk/partition commands | blocked | blocked |

Parsing rules: split on `&&`, `;`, `|`, `||`; classify each segment; the call takes the highest tier found. Treat unknown commands as tier 1 in Ask mode and tier 1 in Auto (run), because failing closed on every unknown would make the terminal unusable. Tier 3 is always blocked, regardless of mode or approval.

### 5.2 Make tier 2 enforcement independent of the flag

This is the one product decision I would push for. The flag should control the noisy part (prompting on every workspace write), not the safety promise. Tier 2 prompts even in Auto. Tier 3 is always blocked. That lets the README say "destructive commands always require approval" without shipping the noisy mode.

### 5.3 Gate the developer/workforce path

`developer.py` should use the same `_gate_tool_if_named` helper, with the mode coming from the chat's `toolkit_config`. Otherwise a trigger can force-push with no prompt while the single agent cannot.

### 5.4 Approval timeout

120s is short for a user reading a 40-line command. Raise to 5 minutes, and on expiry do not say "denied". Emit `expired`, keep the card visible with a "Retry" affordance, and let the agent continue with a non-mutating step. `approval_manager.py:77` is the single constant.

### 5.5 Session allowlist

Add a suppression row above the footer: "Suppress prompts for the rest of this task:", with scope pills:

| Scope | Covers |
| --- | --- |
| File reads | `read_file`, `cat`, `head`, `tail`, `rg`, `grep`, `find` without `-delete` |
| File writes | `write_to_file`, non-deleting `apply_patch`, `mkdir`, `touch` |
| Builds & tests | `npm test`, `pytest`, `tsc --noEmit`, `eslint`, build scripts |
| Dependency installs | `npm install`, `pip install`, `uv add` |
| Git add & commit | `git add`, `git commit`, branch creation |

Reads are the default allowlisted scope: they are tier 0, so a fresh task never prompts for them. Unchecking **File reads** removes it from the TaskLock allowlist, and the gate then requires approval before reads for the rest of the task. That gives the user a real privacy switch without making every task start with a read prompt.

The other four scopes map to tier 1 and are toggles. Multiple scopes can be selected.

Store the selection on the TaskLock, not globally, so a new turn prompts again. Only tiers 0 and 1 are allowlistable. A tier 2 destructive call always prompts; offering suppression there would defeat the point.

### 5.6 Card content

The card extracts the meaningful argument (`ApprovalRequestCard.tsx:76-87`). The approved layout:

- Header: shield icon, **Approval needed**, tier chip (Destructive / Writes files / Read only).
- A one-line plain-language description directly under the title. This replaces the old tool-name + agent subtitle.
- The full command in a scrollable mono block (`max-h-40`), never truncated to one line for tier 2.
- The working directory under the command.
- Footer: "Runs only if you approve." on the left, Deny and Approve on the right. Approve is red for tier 2, green otherwise.
- Expired state: Retry replaces Approve and the footer turns amber.
- Tier 0/1: the scope suppression row above the footer (see 5.5). Tier 2 hides it entirely.

The shared presentational component is `ApprovalRequestCardView`; the store-driven `ApprovalRequestCard` owns the POST and the SSE-cleared state.

---

## 6. Stories

### 6.1 User stories (acceptance criteria)

**S1, destructive command needs approval.**
As a user, when the agent tries `git push --force`, I see a card above the composer with the full command, the branch, and a red "Destructive" label. Approve runs it; Deny returns the agent to planning. Acceptance: the exact command string is visible; Deny produces an `approval_resolved` event and an outcome card; the command does not run.

**S2, read-only command does not prompt.**
`git status`, `rg`, `tsc --noEmit`, `npm test` run with no interruption in both modes. Acceptance: no `approval_request` event is emitted for tier 0.

**S3, deletion is refused.**
Any `rm` attempt returns the safe-mode rejection and no approval card. Acceptance: the agent is told deletion is unavailable and does not retry with a different spelling.

**S4, approval expiry.**
If I do not answer in 5 minutes, the card shows "Expired", the agent receives an expiry result, and it proposes a non-mutating next step. Acceptance: no command ran; the card remains visible until dismissed.

**S5, allow for this task.**
After approving `npm test` with "always allow", subsequent `npm test` calls in the same task do not prompt; a new task prompts again.

**S6, multi-client convergence.**
If the decision is made on another client, this client's card clears and shows the same outcome. Acceptance: both clients show one outcome message, not two.

**S7, worker parity.**
A workforce worker's destructive command prompts the same way the single agent's does.

**S8, kill across turns.**
I ask in a new turn to stop a server started in a previous turn. It stops, and the port is free. Acceptance: `shell_kill_process` resolves the project-level registry.

### 6.2 Storybook stories to add

File: `agent-ui/src/stories/panels/ApprovalRequestCard.stories.tsx`.

The approved stories render the shared `ApprovalRequestCardView` inside a scene
that shows it above the composer, which is where it mounts live:

1. `DestructiveShell` (`git push --force origin main`)
2. `WorkspaceWrite` (`npm install zod`, with the task allowlist checkbox)
3. `FileWrite` (`write_to_file`, path plus the new content)
4. `LongCommand` (multi-line script, proves the block scrolls and does not truncate)
5. `Submitting` (Approve pressed, spinner, both buttons disabled)
6. `Expired` (card in its timeout state, Retry replaces Approve)
7. `NarrowRail` (400px width, the Theia right rail)
8. `ReadOnly` (quiet neutral tier)

A store-driven story is not needed while the view is presentational; once the
backend sends `tier`, `description`, and `working_directory`, add one story that
builds `createChatStoreInstance()` and sets `tasks[demo].activeApproval` to prove
the wiring.

---

## 7. Will the prompt rule and governance conflict?

Yes, if both are added exactly as described. Three concrete collisions:

**Collision 1, double prompt.** The prompt rule says "all dangerous commands prompt the user first". If the agent implements that by calling `ask_human_via_console`, and the gate also fires, the user gets two prompts for one command. Worse, the agent is now blocked waiting for an answer while the approval Future is also waiting for a decision. The 120s timeout can fire while the human is answering the agent's question.

**Collision 2, different definitions of dangerous.** The prompt says tests and eslint are not destructive. The gate prompts on every `shell_exec`, including `ls`. The user sees a prompt for a command the prompt told the agent needs no prompt. One of them is lying.

**Collision 3, enforcement gap.** A prompt rule is advisory; a model can ignore it. The gate is enforcement, but it only covers the single agent and only when the flag is on. If the prompt promises "the user will be asked" in a build where the gate is off, the promise is false. Triggers and workers are the obvious hole.

Resolution, one owner per decision:

- **Backend classifier owns the decision.** Prompt only describes it.
- **Prompt says do not self-ask.** The gate is the only approval mechanism. Remove `ask_human_via_console` from the destructive-command path in the instructions.
- **Tier 3 is always blocked**, in both modes, so the prompt can state it as a fact ("`rm` does not work") rather than a request.
- **Tier 2 always prompts**, even with the flag off, so the safety claim in the README is true.
- **Flag only controls tier 1 prompt volume**, the "ask me before every write" behavior nobody wants on by default.

With that split the two features reinforce each other: the prompt tells the model what will happen, the backend makes it happen, and there is exactly one prompt per command.

---

## 8. Suggested order

1. Terminal fixes 1 to 4 plus tests. This is the freeze, and it is independent of governance.
2. Prompt `<shell_safety>` block in both prompts, remove "Automate Confirmation".
3. `command_policy.py` plus tier 0 and tier 3 only. Ship this ungated.
   **Done 2026-10-18.**
4. Tier 2 ungated, tier 1 behind the existing flag. **Done 2026-10-18.**
5. Developer/workforce gating.
6. Timeout, allowlist, card states, Storybook stories.
