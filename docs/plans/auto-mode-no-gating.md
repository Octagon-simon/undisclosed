# Auto mode must mean no gating

Status: plan only, nothing implemented.
Trigger: a user turned "run automatically" on and still got an approval card for

```
cd .../packages/admin && VITE_API_BASE_URL=http://localhost:3031 \
  npx vite --port 5177 --strictPort > /tmp/vite-5177.log 2>&1
```

Goal: when the mode is AUTO, every command runs. The only things left that can
stop the agent are irreversible deletions and git operations that throw work
away or overwrite a remote. Nothing else may surface a card.

---

## 1. Why the card appeared with the toggle off

Three separate layers, all confirmed by reading the code.

**1. The redirect made it tier 2.** `assess_command` treats any write target
that resolves outside the workspace as `DESTRUCTIVE`
(`brain/app/agent/toolkit/command_policy.py:468-478`). The command writes its log
to `/tmp/vite-5177.log`, which is outside the project, so the whole line became
tier 2 with the reason "writes /tmp/vite-5177.log outside the workspace; that
needs approval in every mode".

**2. The terminal is wrapped even in AUTO.** `toolkit_assembler.py:955-968`
gates `shell_exec`, `shell_write_content_to_file` and `shell_write_to_process`
unconditionally, and `_governance_mode` defaults to `auto`
(`toolkit_assembler.py:134`). So AUTO does not mean "no wrapper"; it means
"wrapper with the flag off".

**3. The wrapper prompts for tier 2 regardless of mode.**

```python
# brain/app/agent/toolkit/governance_toolkit.py:589
needs_approval = tier >= CommandTier.DESTRUCTIVE or (
    effective_mode == GovernanceMode.ASK
    and tier >= CommandTier.WORKSPACE_WRITE
)
```

That single line is the reported bug. With the flag off, the first clause still
forces a card for every tier 2 action.

Same shape elsewhere:

- git tools are wrapped in AUTO (`toolkit_assembler.py:979-988`)
- GitHub write tools are wrapped in AUTO (`toolkit_assembler.py:861-870`)
- workers call `gate_worker_tools` with no mode (`developer.py:206`,
  `chat_service.py:3107`), so they resolve `session_governance_mode(...)` and
  fall back to ASK when the task lock has no recorded mode
  (`governance_toolkit.py:415-432`)
- a read-privacy branch prompts for file reads "in every mode"
  (`governance_toolkit.py:595-603`), so a `cat` can still ask in AUTO if the
  task allowlist lost `FILE_READS`

So the fix is not in the UI or the toggle. The toggle reaches the brain
correctly (`chatStore.ts:2523` sends `governance: { mode }`, the badge reads the
same store at `RightAgentPanel.tsx:96`). The gate itself is what ignores it.

---

## 2. The rule we want

AUTO keeps exactly two reasons to ask:

1. **Deletion.** The `delete_files` tool, and shell commands that delete files
   whose target the classifier cannot scope.
2. **Git history and remote changes.** `git push`, `git reset`, `git clean`,
   `git rebase`, `git filter-branch`/`filter-repo`, `git restore`,
   `git checkout -- .`, `git branch -d/-D/-m/-M`, `git tag -d`,
   `git stash drop|clear`, and the `git_push` tool.

Everything else runs with no card. Tier 3 stays as it is: a policy refusal, not
an approval prompt, and approval never overrides it
(`governance_toolkit.py:560-574`).

### Before and after

| Call | AUTO today | AUTO after |
| --- | --- | --- |
| read-only (`ls`, `git status`) | runs | runs |
| workspace write (`mkdir`, `npm i`) | runs | runs |
| write outside workspace (`> /tmp/log`, dev server) | **asks** | runs |
| `shell_write_to_process` (stdin to a live process) | **asks** | runs |
| tests / builds / coverage | **asks** when the command is tier 2 | runs |
| deploy and cloud CLI (`vercel`, `aws`, `kubectl`, `terraform`) | **asks** | runs |
| SQL that drops or truncates | **asks** | runs |
| GitHub and Mongo writes | **asks** | runs |
| `git push`, `reset`, `clean`, `rebase`, `restore`, `stash drop` | **asks** | asks |
| `delete_files` tool | runs | **asks** (new) |
| `rm`, `rmdir`, `shred`, `sudo`, `dd`, `mkfs`, `find -delete`, `xargs rm` | refused | refused |

Two of those rows are deliberate consequences of your instruction, and they are
the ones to sanity-check:

- **Deploys stop asking in AUTO.** `_DEPLOY_BINARIES` returns tier 2 for
  anything that is not a read subcommand (`command_policy.py:1289-1293`), so
  `vercel deploy` currently asks in AUTO and would stop.
- **GitHub and Mongo writes stop asking in AUTO.** Both are tier 2 by field
  (`governance_toolkit.py:124-125`).

If either should stay gated, add it to the protected set in Phase 2. Nothing
else in the plan changes.

---

## 3. Implementation

### Phase 1: a second axis on the classifier

`CommandTier` answers "how bad". We need "is this reversible". Folding
irreversibility into the tier would break ASK, which must keep prompting for
every write.

`brain/app/agent/toolkit/command_policy.py`

- Add `irreversible: bool = False` and `irreversible_reason: str = ""` to
  `CommandAssessment` (currently lines 44-55). Keep `tier` untouched.
- Add `_is_irreversible(name: str, args: list[str], tier, reason) -> bool` used
  per segment in `assess_command` (lines 456-467), OR'd across segments the same
  way `tier` is.
- Rules:
  - `git` with a subcommand in the destructive set from `_classify_git`
    (lines 1381-1422): push, reset, clean, rebase, filter-branch, filter-repo,
    restore, `checkout --`, `branch -d/-D/-m/-M`, `tag -d`, `stash drop|clear`.
    `git rm` is already tier 3.
  - a shell delete call the classifier cannot scope (line 492-497, currently
    tier 2 "deletes files it cannot scope").
  - deletion targets outside the workspace stay tier 3, unchanged.
- Do not mark `> /tmp/log`, deploys, SQL, `kill`, or `mount` as irreversible.
  That is the whole point of the change.

### Phase 2: stop the wrapper from asking in AUTO

`brain/app/agent/toolkit/governance_toolkit.py`

- Add `PROTECTED_TOOL_NAMES = frozenset({"delete_files"})` next to
  `_TERMINAL_TOOL_TIERS` (line 137).
- Add `_call_is_irreversible(...)` mirroring `_call_tier` (line 176): true for a
  protected tool name, else the classifier's `irreversible` flag.
- Rewrite the rule at line 589:

```python
if effective_mode is GovernanceMode.ASK:
    needs_approval = tier >= CommandTier.WORKSPACE_WRITE
else:
    needs_approval = irreversible
```

- Keep `suppressed` and the `BLOCKED` early return exactly as they are, but move
  the read-privacy branch (lines 595-603) under ASK. It currently re-enables
  prompts in AUTO even for a read-only `cat`, which contradicts the toggle.
- Update the module docstring (lines 16-34). It documents the old matrix
  ("DESTRUCTIVE prompts in every mode, including AUTO") and would become a lie.

### Phase 3: wrap file tools in AUTO too

`brain/app/agent/factory/toolkit_assembler.py:623-636`

The file tools are wrapped only when the mode is ASK, so `delete_files` cannot be
protected in AUTO. Drop the `if governance_mode is GovernanceMode.ASK:` guard and
rely on the wrapper rule. `write_to_file` and `edit_file` still run in AUTO
because they are not protected; `delete_files` asks.

### Phase 4: the worker fallback

No code change planned, but it needs a test. `session_governance_mode` defaults
to ASK when the task lock has no recorded mode, which is the fail-closed choice
you want for a worker whose session is unknown. In a normal AUTO turn the
assembler records the mode first (`toolkit_assembler.py:593`), so workers inherit
it. Add one test that proves a developer worker in an AUTO session runs a
`> /tmp/x` command with no card.

---

## 4. Tests

- `brain/tests/app/agent/toolkit/test_governance_toolkit.py:271-300`
  `test_destructive_prompts_in_auto` and `test_destructive_denied_in_auto`
  assert the exact behavior we are removing. Replace them with:
  - `test_outside_workspace_write_runs_in_auto` (the reported command)
  - `test_git_push_prompts_in_auto`
  - `test_delete_files_prompts_in_auto`
  - `test_write_to_file_runs_in_auto`
- `test_governance_toolkit.py:976` `test_worker_destructive_command_prompts_even_in_auto`
  flips to "runs".
- `brain/tests/app/agent/toolkit/test_command_policy.py`: add irreversible cases
  (`git push`, `git reset --hard`, `git clean -fd`, `git checkout -- .`,
  `git stash drop`, a scoped `python -c` delete) and negative cases
  (`> /tmp/log`, `vercel deploy`, `npm i`, `kill 123`).
- ASK coverage must not move: one test per tier asserting the card still appears.

Verification before commit: `pytest brain/tests/app/agent/toolkit/`, `pyright` on
the two touched modules, and `./scripts/check-license-headers.sh`.

---

## 5. Risks and edges

- **Loss of the "prompt in every mode" safety net.** That net is what caused the
  false positive. The replacement is narrower and deliberate: deletion and git
  history only.
- **`git mv` and `git apply`** stay tier 1, so AUTO runs them. They can overwrite
  files, but they are workspace writes, not deletion, and you asked for writes to
  run.
- **`shell_write_to_process`** (stdin to an already-running process) is tier 2
  today and will run in AUTO. If that feels too loose, it is a one-line addition
  to `PROTECTED_TOOL_NAMES`.
- **Existing tasks** reuse the recorded session mode; a task started in ASK keeps
  asking until a new turn records AUTO. That is unchanged behavior and matches
  "applies to tasks started after this is turned on" in the settings copy
  (`setting.json:466`).

## 6. Open decisions

1. Protected set: deletion plus git history/remote only (recommended, matches
   your message), or also deploys, cloud CLIs, and database drops?
2. Tier 3: keep refusing `sudo`, `shutdown`, `dd`, `mkfs` in AUTO (recommended),
   or let AUTO run those too?

Estimated diff: about 90 lines of Python, about 150 lines of tests, no UI change.
