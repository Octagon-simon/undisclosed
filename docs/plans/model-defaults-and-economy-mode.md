# Model defaults, vision model, and economy mode

Status: planned. Nothing below is implemented except the vision-model
resolution that already ships in `brain/app/utils/vision_backend.py`.

## Why

Today a conversation has one model. Three problems follow from that:

1. Image work is forced through the chat model. A coding model such as
   `deepseek-chat` cannot see a screenshot, so `read_image` and image captions
   fail or silently degrade.
2. Users cannot say "use this model for text and that model for images" once,
   and have it stick across chats.
3. A strong model pays strong-model prices for every mechanical step of a
   task, even the parts a cheap model can do.

This document covers the first two as model defaults, and the third as
economy mode. They share the same underlying idea: a task is a pipeline of
roles, not a single model choice.

## Part 1: user-selectable default text and vision models

### What the user sees

A new section in Agents > Models:

```
Default models
  Text       [ deepseek-v4-flash        v ]   used for chat and planning
  Vision     [ deepseek-v4-flash-vision-exp v ]   used for images and screenshots
  [ ] Ask me per conversation
```

The pickers list only models the user has configured (the rows in
`~/.undisclosed/providers.json`). Vision options are filtered with
`model_capabilities.model_supports_vision`; text options are unfiltered.

### Behavior

- A new conversation starts with the saved defaults.
- The in-chat model picker still allows a per-conversation override for the
  text model. The override does not change the saved default unless the user
  chooses "Set as default".
- The vision model is not exposed per conversation. It is infrastructure: any
  tool that sends image blocks (`read_image`, short-lived caption agents,
  future OCR fallbacks) resolves it through one helper.
- When no vision model is configured, image tools return an actionable error
  instead of sending an image to a text model. That is the current behavior of
  `vision_backend_for`.

### Storage

Persist in `~/.undisclosed/settings.json` (new file, one writer):

```json
{
  "default_models": {
    "text": {"provider_id": 1, "model_type": "deepseek-v4-flash"},
    "vision": {"provider_id": 10, "model_type": "deepseek-v4-flash-vision-exp"}
  }
}
```

Store the provider id as well as the model id. The same model id can exist
under two providers (local vLLM and a hosted endpoint), and the API key and
base URL live on the provider row, not on the model.

### Resolution order

For the text model, highest priority first:

1. Per-conversation selection in the chat payload.
2. `default_models.text`.
3. Existing fallback (`providers.json` row with `prefer: true`).

For the vision model:

1. `UNDISCLOSED_VISION_MODEL` environment variable. Keeps headless and CI
   runs deterministic.
2. `default_models.vision`.
3. First configured row where `model_supports_vision` is true, preferring ids
   containing `vision`, then the `prefer` row.

`vision_backend_for()` already implements 1 and 3; step 2 slots in between.

### Backend work

- Extend the settings API (`chat_platform_controller` already owns
  `providers.json`) with `GET/PUT /settings/default-models`.
- Validate on write: the provider must exist, the model id must match the row,
  and a vision default must pass `model_supports_vision`. Reject invalid
  writes with a typed error so the UI can show it inline.
- `vision_backend_for()` reads the settings file and caches the built backend
  per `(platform, model, key, url)`. Cache invalidation: drop the entry when
  the settings file's mtime changes, so editing the model in the UI takes
  effect without a brain restart.
- The agent assembler keeps passing the conversation's text model. Only
  image-only helpers switch to the vision model.

### UI work

- Add the two pickers to the Models page, grouped by provider with the
  existing provider logo components.
- Show a warning row when no vision model is configured and image tools are
  available: "Screenshots will not be readable until you pick a vision model."
- Keep the chat composer picker unchanged except for a "Set as default"
  action in its footer.

## Part 2: economy mode

### The idea

Two models, two roles:

- Planner (strong, expensive): reads the request, explores the repo, resolves
  ambiguity, and writes a concrete plan.
- Executor (cheap, fast): receives the plan and carries out individual steps.

The saving comes from not paying planner prices for mechanical edits, test
runs, and file reads. The risk is that a weak executor silently misreads the
plan, so the handoff has to be structured and checkable.

### Flow

```
user request
   |
   v
planner model  --(reads files, runs searches, writes plan)-->  plan.md
   |                                                              |
   |                                                              v
   |                                                    executor model
   |                                                    step 1 -> verify
   |                                                    step 2 -> verify
   |                                                    ...
   v
planner reviews the final diff and the verification receipts
```

The planner does not hand off a prose answer. It writes a plan with explicit
steps, each step carrying:

- the files it may touch
- the exact change or command
- the verification command and expected result
- a stop condition ("if the test still fails after this step, return to the
  planner")

That structure is what makes a weak executor viable. It also gives the
planner a cheap way to audit: run the same verification commands and compare.

### Where the switch happens

Economy mode is a per-conversation setting, off by default:

```
[ ] Economy mode   Planner [ claude-opus-4-1 v ]  Executor [ deepseek-v4-flash v ]
```

Implementation sketch:

1. Turn starts on the planner model, with the normal tool set.
2. The planner is instructed to produce a plan file under
   `~/.undisclosed/plans/<task_id>.md` before any mutation. Planning-only
   tools (read, search, git status) stay available; write and shell tools are
   withheld until the plan file exists.
3. A `handoff` step swaps `task_lock`'s agent model to the executor and loads
   the plan as the active instruction set. The executor sees the plan and the
   current file state, not the planner's full conversation.
4. Each executor step ends with a verification receipt (command, exit code,
   output digest). Failures return control to the planner, which revises the
   plan or takes over the step.
5. The final answer is written by the planner after it reads the receipts.

### Guardrails

- Cap planner re-entries per task (default 3) so a looping executor cannot
  burn the strong model's budget.
- Cap total executor steps per plan step (default 5).
- Log token spend per role. Without this, "economy" is a claim, not a
  measurement.
- If the executor's model does not support tool calling, refuse to enable
  economy mode rather than silently falling back.
- Never let the executor edit the plan file.

### Why this should save tokens

The planner's context is the expensive part: large repo reads, long tool
outputs, repeated reasoning. The executor gets the distilled plan plus the
files it needs. Even if the executor uses twice as many turns, its per-token
price is typically an order of magnitude lower. The saving is real only when
the plan is specific enough that the executor does not re-explore; that is the
metric to watch.

## Phases

1. Settings file, default-model API, and Models-page pickers. Wire the vision
   default into `vision_backend_for()`. Ship this first; it fixes image tools
   for text-only chat models today.
2. Planner-only phase with the plan file and write-tool gating. No executor
   yet. This proves the plan format is good enough to act on.
3. Executor handoff with verification receipts and re-entry caps.
4. Spend reporting per role, shown in the task's execution summary.

## Open questions

- Should economy mode be per conversation or per project? Project-level makes
  sense for long-running work, conversation-level for one-off tasks.
- Does the planner keep its full tool history after handoff, or restart from
  the plan? Restarting saves tokens; keeping history helps when the executor
  asks a clarifying question.
- How does the user see the handoff? The execution summary should show the
  planner and executor as distinct rows, with the plan card between them,
  rather than pretending one model did everything.
- What happens on brain restart mid-task? The plan file survives; the executor
  state does not. Resume from the last completed step in the plan.
