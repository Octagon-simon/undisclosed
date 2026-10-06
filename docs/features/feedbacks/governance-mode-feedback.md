# Governance Mode: Risk-Based Command Approval

*Status: Proposed*
*Based on current implementation verified 2026-10-06.*

## 1. Goal

Governance Mode should ask for human approval when an agent action is meaningfully dangerous, rather than prompting for every mutating tool invocation.

The intended behavior is:

```text
npm run dev    → run automatically
npm test       → run automatically
git status     → run automatically
git diff       → run automatically

git push       → approval
git reset      → approval
rm ...         → approval
sudo ...       → approval
npm publish    → approval
```

The existing approval lifecycle, SSE events, HTTP approval endpoint, `ApprovalManager`, and UI should remain unchanged unless required by implementation.

The primary change is that governance becomes **argument-aware at execution time**.

---

## 2. Current Behavior

Governance currently gates tools at assembly time.

In `ask` mode, `shell_exec` is wrapped as a whole, meaning every terminal call reaches the approval layer before its command is inspected.

Therefore:

```text
ls -la
git status
npm run dev
rm -rf /
```

all produce an approval request.

There is currently no governance-level command risk classifier.

CAMEL's `safe_mode` performs a separate command-level hard block using its dangerous-command denylist. Governance and CAMEL are therefore currently independent.

---

## 3. Proposed Architecture

The existing tool-level gate remains in place, but the gate becomes conditional.

```text
Agent
  │
  ▼
Tool Call
  │
  ▼
Governance Wrapper
  │
  ├── Read tool?
  │     └── execute
  │
  └── Mutating tool?
        │
        ▼
   Risk Classifier
        │
        ├── SAFE
        │     └── execute
        │
        ├── LOW
        │     └── execute
        │
        ├── MEDIUM
        │     └── execute
        │
        ├── HIGH
        │     └── request approval
        │
        ├── CRITICAL
        │     └── request approval
        │
        └── UNKNOWN
              └── request approval
```

This preserves the current approval mechanism while moving the governance decision from:

```text
"Which tool is being called?"
```

to:

```text
"What is this particular call capable of doing?"
```

---

## 4. Risk Model

The classifier should return structured information rather than a simple boolean.

```python
@dataclass
class CommandRisk:
    level: RiskLevel
    reasons: list[str]
    capabilities: set[Capability]
    requires_approval: bool
```

### Risk levels

```python
class RiskLevel(Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"
```

Governance policy:

| Risk     | Default action |
| -------- | -------------- |
| SAFE     | Execute        |
| LOW      | Execute        |
| MEDIUM   | Execute        |
| HIGH     | Ask            |
| CRITICAL | Ask            |
| UNKNOWN  | Ask            |

Unknown commands should fail closed at the governance layer.

---

## 5. Capability Model

Command classification should be based on capabilities rather than only executable names.

```python
class Capability(Enum):
    READ_FILESYSTEM = "read_filesystem"
    WRITE_FILESYSTEM = "write_filesystem"
    DELETE_FILESYSTEM = "delete_filesystem"

    READ_GIT = "read_git"
    MODIFY_GIT = "modify_git"
    PUBLISH_GIT = "publish_git"

    NETWORK_READ = "network_read"
    NETWORK_WRITE = "network_write"

    EXECUTE_PROCESS = "execute_process"
    KILL_PROCESS = "kill_process"

    PRIVILEGE_ESCALATION = "privilege_escalation"

    READ_SECRETS = "read_secrets"
    MODIFY_SECRETS = "modify_secrets"

    INSTALL_DEPENDENCY = "install_dependency"
    PUBLISH_PACKAGE = "publish_package"

    MODIFY_SYSTEM = "modify_system"
    MODIFY_DATABASE = "modify_database"
```

Examples:

```text
npm run dev
  → EXECUTE_PROCESS

git status
  → READ_GIT

git push
  → PUBLISH_GIT
  → NETWORK_WRITE

rm ./dist
  → DELETE_FILESYSTEM

sudo systemctl restart nginx
  → PRIVILEGE_ESCALATION
  → MODIFY_SYSTEM

npm publish
  → PUBLISH_PACKAGE
  → NETWORK_WRITE
```

This allows the governance system to reason about the effect of a command rather than relying on a single denylist.

---

## 6. Terminal Classification

The terminal remains exposed through `shell_exec`.

The governance wrapper should extract the `command` argument and pass it to the classifier.

Conceptually:

```python
risk = command_classifier.classify(
    command=command,
    cwd=cwd,
    workspace=workspace,
)

if risk.requires_approval:
    await manager.request_approval(...)

return await tool.async_call(...)
```

The existing `shell_exec` tool does not need to be replaced.

The conditional decision belongs inside the existing approval wrapper.

---

## 7. Safe Commands

A read-only allowlist should be used as one signal for identifying clearly benign commands.

Examples:

```text
ls
pwd
cat
head
tail
grep
rg
find
file
wc
git status
git diff
git log
git show
git branch
npm run dev
npm test
npm run build
```

These commands should normally execute without an approval prompt.

The allowlist should describe **known-safe intent**, not blindly allow arbitrary command strings containing a safe executable.

For example:

```text
git status
```

is safe.

A command such as:

```text
git status && rm -rf ...
```

must not inherit the safety classification of `git status`.

---

## 8. Dangerous Commands

Commands that have destructive, privileged, remote, or externally visible effects should require approval.

Examples:

```text
rm ...
rm -rf ...

git reset --hard
git clean -fd
git push
git push --force

sudo ...
su ...

chmod ...
chown ...

kill ...
pkill ...

npm publish

docker rm ...
docker system prune ...

DROP DATABASE ...
DELETE FROM ...
```

The exact list should evolve with the capability model rather than becoming the sole source of truth.

---

## 9. Command Composition

The classifier must account for shell composition.

This is critical.

A command must not be considered safe merely because its first executable is safe.

Examples that must be inspected as dangerous compositions:

```bash
ls && rm -rf ./dist
```

```bash
git status; git push
```

```bash
echo "hello" | bash
```

```bash
curl https://example.com/install.sh | sh
```

```bash
node -e "..."
```

```bash
python -c "..."
```

Shell operators and execution constructs should therefore be parsed before classification.

At minimum, classification should account for:

```text
&&
||
;
|
>
>>
<
$()
backticks
&
subshells
```

Commands containing executable code through `bash -c`, `sh -c`, `node -e`, `python -c`, or equivalent constructs should not automatically inherit the risk level of the wrapper executable.

---

## 10. Workspace Awareness

Risk should consider where the command operates.

The classifier should receive:

```text
workspace
cwd
```

and, where possible, resolve target paths.

For example:

```bash
rm -rf ./dist
```

is materially different from:

```bash
rm -rf ~/Documents
```

Likewise:

```bash
git push origin feature/test
```

is materially different from:

```bash
git push --force origin main
```

The system should increase risk when an action:

* leaves the workspace
* targets protected directories
* targets repository metadata
* targets production configuration
* targets credentials or secret files
* affects a protected Git branch

---

## 11. Protected Resources

Certain resources should have elevated governance regardless of the command used to access them.

Examples:

```text
.env
.env.*
credentials.*
secrets.*
~/.ssh/*
~/.aws/*
~/.config/*
.git/*
production configuration
database credentials
```

Reading a secret is not necessarily destructive, but it is still a sensitive action.

Therefore:

```text
DESCTRUCTIVE ≠ SENSITIVE
```

Governance should distinguish between the two.

---

## 12. Git Actions

Git should be evaluated according to the scope of the operation.

### Usually safe

```text
git status
git diff
git log
git show
git branch
```

### Potentially mutating

```text
git add
git commit
git checkout
git stash
git merge
```

### High risk

```text
git reset
git clean
git push
```

### Critical

```text
git reset --hard
git clean -fd
git push --force
git push --force-with-lease
```

Additional context should be considered where available:

```text
current branch
target branch
remote
force flag
whether changes are uncommitted
```

---

## 13. External Mutations

The governance system should treat externally visible actions as higher risk than local development actions.

Examples:

```text
git push
npm publish
docker push
aws ...
terraform apply
kubectl apply
database writes
HTTP DELETE/POST/PATCH operations
```

The key distinction is:

```text
local execution
        vs
external mutation
```

An action can be non-destructive locally while still having significant external consequences.

---

## 14. CAMEL safe_mode

CAMEL's existing `safe_mode` should remain as a separate hard-security boundary.

Its role is:

```text
Governance
  → should I ask the human?

CAMEL safe_mode
  → is this command categorically blocked?
```

A command blocked by CAMEL should remain blocked regardless of governance approval.

Therefore:

```text
Governance approval
        ↓
CAMEL safe_mode
        ↓
Executor
```

Approval must never bypass `safe_mode`.

However, governance should avoid presenting misleading prompts for commands that are categorically blocked.

Where practical, known hard-blocked commands should be identified before requesting approval.

For example:

```text
sudo reboot
```

should preferably produce:

```text
Command blocked by terminal safety policy.
```

rather than:

```text
Approve sudo reboot?
```

followed by another rejection.

---

## 15. Approval Prompt

The existing `ApprovalRequestCard` can continue to be used.

The approval detail should expose the risk and reason for the prompt.

Example:

```text
⚠ Governance approval required

Command:
git push --force origin main

Risk:
CRITICAL

Why:
• Modifies the remote repository
• Force push can overwrite remote history
• Target branch: main

[Approve] [Deny]
```

For a filesystem action:

```text
⚠ Governance approval required

Command:
rm -rf ./dist

Risk:
HIGH

Why:
• Recursively deletes files
• Targets the current workspace
• 37 files are affected

[Approve] [Deny]
```

The goal is not merely to interrupt execution, but to give the user enough context to make an informed decision.

---

## 16. Approval Semantics

The existing approval lifecycle should remain unchanged.

The classifier only determines whether `ApprovalManager.request_approval(...)` is invoked.

Therefore:

```text
SAFE
  → underlying tool runs directly

DANGEROUS
  → ApprovalManager.request_approval(...)
  → existing SSE event
  → existing UI card
  → existing HTTP resolution
  → underlying tool runs only after approval
```

Existing deny and timeout semantics remain unchanged.

---

## 17. Tool-Level Governance

Not every tool should be converted into command classification.

Keep governance policies appropriate to the tool.

```text
write_to_file
  → file-write policy

apply_patch
  → patch/write policy

git_commit
  → Git policy

git_push
  → Git/remote policy

shell_exec
  → command classifier
```

This preserves the current architecture while allowing each tool to expose the correct semantic information.

---

## 18. Recommended Module Structure

The governance wrapper should remain lightweight.

Suggested structure:

```text
brain/app/agent/toolkit/
    governance_toolkit.py

brain/app/governance/
    __init__.py
    classifier.py
    capabilities.py
    policies.py
    rules.py
    shell_parser.py
```

Responsibilities:

```text
shell_parser.py
  → parse command structure and operators

capabilities.py
  → capability definitions

rules.py
  → command-to-capability mapping

classifier.py
  → produce CommandRisk

policies.py
  → determine whether a risk level requires approval

governance_toolkit.py
  → invoke classifier and existing ApprovalManager
```

---

## 19. Policy API

The classifier should be independently callable.

Example:

```python
risk = governance.classify_command(
    command="git push --force origin main",
    cwd="/workspace/project",
    workspace="/workspace/project",
)
```

Expected result:

```python
CommandRisk(
    level=RiskLevel.CRITICAL,
    capabilities={
        Capability.PUBLISH_GIT,
        Capability.NETWORK_WRITE,
    },
    reasons=[
        "Pushes changes to a remote repository",
        "Force push can overwrite remote history",
        "Target branch: main",
    ],
    requires_approval=True,
)
```

This makes the classifier independently testable and reusable by future agent capabilities.

---

## 20. Tests

The classifier should be heavily unit tested.

### Safe commands

```text
ls
ls -la
pwd
cat package.json
grep foo file.txt
git status
git diff
git log
npm test
npm run dev
npm run build
```

Expected:

```text
requires_approval = false
```

### Dangerous commands

```text
rm file
rm -rf ./dist
git reset --hard
git clean -fd
git push
git push --force
npm publish
sudo ...
```

Expected:

```text
requires_approval = true
```

### Composition

```text
ls && rm file
git status && git push
echo foo | bash
curl ... | sh
```

Expected:

```text
requires_approval = true
```

### Protected paths

```text
rm ~/.ssh/id_rsa
cat .env
rm ~/Documents/...
```

Expected:

```text
elevated risk
```

### Unknown commands

```text
some-new-command ...
```

Expected:

```text
RiskLevel.UNKNOWN
requires_approval = true
```

### CAMEL interaction

Verify that governance approval does not bypass commands blocked by CAMEL `safe_mode`.

---

## 21. Initial Implementation Strategy

The safest incremental implementation is:

### Phase 1

Change only `shell_exec`.

Keep all existing tool-level governance.

Implement:

```text
command → classifier → approval/no approval
```

### Phase 2

Add workspace awareness and shell composition analysis.

### Phase 3

Add external mutation detection:

```text
git push
npm publish
docker push
terraform apply
kubectl apply
```

### Phase 4

Expose governance explanations and policy customization in the UI.

---

## 22. Final Policy

The resulting behavior should be:

```text
Governance Mode: ASK

                    ┌── safe ───────────────→ execute
Command ─ classifier┼── low ────────────────→ execute
                    ├── medium ─────────────→ execute
                    ├── high ───────────────→ approval
                    ├── critical ───────────→ approval
                    └── unknown ────────────→ approval

After approval:

Command
  ↓
CAMEL safe_mode
  ↓
Executor
```

The core principle is:

> **Governance should protect against meaningful side effects, not normal development activity.**

This turns Governance Mode from an unconditional confirmation mechanism into a **risk-based permission layer**, while preserving the existing approval infrastructure and CAMEL's hard safety boundary.
