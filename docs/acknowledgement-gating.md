# Turn-start Acknowledgement — Feature Notes & Open Problem

_Status: implemented (env-gated, off by default). Gating strategy is the open question._

---

## 1. Goal

When the agent starts a turn, show a short, human, contextual line that conveys
presence — e.g.:

> **You:** fix the 429 errors
> **Agent:** _On it — I'll add retry/backoff to the Figma calls._
> ▸ Worked for 12s · 3 files read …
> **Agent:** _(final answer)_

It should read like the agent's own opening line, **before** the work summary.

## 2. Hard constraint (must never regress)

The acknowledgement must **never enter the agent's message history**. A previous
regression ("let me… let me… let me…") happened when per-tool-call preambles got
concatenated into the stored answer and re-fed to the model on later turns
(context bloat). The ack is cosmetic only and must stay fully decoupled from the
turn agent's memory.

## 3. The problem we're stuck on

The ack fires on **trivial conversational turns** where it's redundant and reads
like a duplicate answer:

> **You:** How are you
> **Agent (ack):** _I'm doing wonderfully, thank you—ready to help you with whatever you need!_
> ▸ Worked for 3s
> **Agent (answer):** _I'm doing well, thanks for asking. How can I help you today?_

Two dueling shots at the same question. We want the ack **only on long tasks or
tasks that call tools** — i.e. turns with real work — and **not** on small
questions.

**Current discomfort (why this doc exists):**
- The current fix is **time-gating** (see §5), which feels arbitrary.
- Even with time-gating, a *slow-but-trivial* answer can still slip an ack
  through, so small questions aren't reliably excluded.
- Delaying the ack also weakens the "immediate presence" idea it started from.

## 4. How the feature works today (data flow)

**Backend — `brain/app/service/single_agent_service.py`**
- `_ACK_INSTRUCTION` — system prompt: "one short warm sentence, don't answer,
  don't list steps."
- `_emit_acknowledgement(agent, question, task_lock, task_id, delay=0.0)`
  - Builds a **throwaway** `ChatAgent(system_message=_ACK_INSTRUCTION,
    model=agent.model_backend, tools=[], stream_accumulate=True)`.
  - The single agent forces `stream=True`, so `astep` returns an
    `AsyncStreamingChatAgentResponse`; we **consume the stream** and keep the
    final full sentence. (Reading `.msg` directly returns empty — this was a
    real bug: "[ack] model returned no content" in ~1 ms.)
  - 8 s `asyncio.wait_for` timeout around consumption.
  - Emits `ActionAcknowledgeData(process_task_id, data)` onto the task queue.
- `_ack_enabled()` — gate on env `AGENT_ACK_ENABLED` (off unless `1/true/yes/on`).
- `_action_to_sse` — maps the event to
  `{"step":"acknowledge","data":{"acknowledgement": "...", "process_task_id": "..."}}`.

**Event model — `brain/app/service/task.py`**
- `Action.acknowledge` enum member + `ActionAcknowledgeData` (in the `ActionData`
  union).

**Frontend**
- `agent-ui/src/types/constants.ts` — `ACKNOWLEDGE: 'acknowledge'`.
- `agent-ui/src/store/chatStore.ts` — per-task field `acknowledgement`, actions
  `setAcknowledgement` / `clearAcknowledgement`; SSE handler on
  `step === AgentStep.ACKNOWLEDGE`; cleared at each turn start alongside
  `clearLiveReasoning`.
- `agent-ui/src/components/ChatBox/UserQueryGroup.tsx` — renders the ack via
  `AgentMessageCard` (same component as the real answer) **above** the
  `TaskWorkLogAccordion` ("Worked for Xs"), so it reads as the opener.

**Env knobs**
- `AGENT_ACK_ENABLED=1` — master on/off.
- `AGENT_ACK_DELAY_MS=4000` — current time-gate threshold (see §5).

## 5. Current gating implementation (time-based delay + cancel)

In `run_turn` (`single_agent_service.py`):
1. After `emit_task_started`, if enabled, schedule
   `asyncio.create_task(_emit_acknowledgement(..., delay=_ack_delay_seconds()))`.
2. The task first `await asyncio.sleep(delay)`, then generates + emits.
3. After `_response_content(...)` returns (turn done), if the ack task is still
   pending, **cancel it**.

**Effect:** turns that finish before `delay` (trivial chit-chat) cancel the ack →
no ack. Turns that outlast `delay` (long / tool work) emit it mid-work.

**Why it's unsatisfying:**
- `delay` is an arbitrary wall-clock threshold; model latency varies per
  machine / model, so the boundary between "trivial" and "real" drifts.
- A slow trivial answer (> delay) still gets an ack.
- The ack is delayed by `delay` (+~1s to generate), so for long tasks it appears
  several seconds in, not immediately.

## 6. Signals available in the codebase (for a better gate)

- **First tool call** — `_response_content()` already tracks tool-call
  boundaries via the cumulative `info["tool_calls"]` count (`_seen_tool_calls`).
  This is the cleanest "this turn is doing real work" signal, but it lives
  inside the streaming loop we deliberately hardened (segment-accumulation fix),
  so touching it carries regression risk.
- **Tool-RAG router decision** — `reconcile_agent_tools_routed(...)` runs
  **before** the step and decides which capabilities/tools the message needs
  from a compact catalog (`UNDISCLOSED_TOOL_ROUTER`). It selects tools but does
  not guarantee the model calls them. Available with no extra model call.
- **Elapsed time** — current approach (§5).
- **A dedicated fast pre-classifier** — a separate cheap call at turn start:
  "is this trivial chit-chat or a task with real work?" Precise-ish, but adds a
  model call + latency to every turn and can misclassify.

## 7. Options to research (neutral trade-off table)

| # | Strategy | Fires ack when… | Pros | Cons |
|---|----------|-----------------|------|------|
| A | **Time delay + cancel** _(current)_ | turn outlasts `AGENT_ACK_DELAY_MS` | isolated, simple, no extra model call for short turns | arbitrary threshold; slow-trivial leaks; ack delayed (less "immediate") |
| B | **First tool call** | the turn actually calls a tool | precise "real work"; excludes chit-chat cleanly | touches hardened streaming loop; misses long *no-tool* tasks; ack appears only after model commits to a tool |
| C | **Router signal** | pre-step router says task needs non-core tools | reuses an existing pre-step decision; no extra call; can fire immediately | router picks tools ≠ model uses them; may over/under-fire |
| D | **Pre-classifier** | a cheap classifier labels the turn "real task" | immediate ack for real tasks, none for chit-chat | extra model call + latency on every turn; classification errors; cost |
| E | **Hybrid (B + time fallback)** | first tool call OR turn outlasts a longer delay | covers both "tool" and "long no-tool" | most code; two mechanisms to reason about |
| F | **Drop the feature / manual** | never (or only when user opts in) | zero risk | loses the presence UX |

## 8. Design questions for the research

1. Is "**real work**" best defined as _tool use_, _elapsed time_, or _predicted
   intent_? (They mostly overlap but diverge on: slow trivial answers, and long
   no-tool writing/reasoning tasks.)
2. Is an **immediate** ack important, or is a slightly delayed one acceptable if
   it's more accurate? (B/C can be immediate-ish; A cannot.)
3. Is one **extra small model call per turn** (option D) acceptable for accuracy,
   given the ack already costs one call when it fires?
4. Acceptable **false-positive rate** — how bad is an occasional ack on a small
   question vs. a missed ack on a real task?
5. Should this ever extend to **workforce mode**? (Currently single-agent only;
   `chat_service.py` routes `session_mode === "single-agent"` → `single_agent_solve`.)

## 9. Current recommendation (mine, for reference)

If precision on "small questions" is the priority: **Option B (first tool call)**,
optionally **E** to also cover long no-tool tasks. It defines "real work" by
what the turn actually does, not a timer. The cost is editing the streaming loop,
which needs care given the segment-accumulation history. If you'd rather not
touch that path, **C (router signal)** is the lowest-risk "immediate + no extra
call" middle ground, accepting some over/under-fire.

## 10. Toggle / revert

- Off instantly: unset `AGENT_ACK_ENABLED` (or set to `0`) and restart the brain.
  No frontend rebuild needed to disable (no event ⇒ nothing renders).
- Full revert touch-points: `_emit_acknowledgement` / `_ack_enabled` /
  `_ack_delay_seconds` / scheduling in `run_turn` / `_action_to_sse` branch
  (`single_agent_service.py`), `Action.acknowledge` + `ActionAcknowledgeData`
  (`task.py`), and the frontend `ACKNOWLEDGE` constant / store field / handler /
  `UserQueryGroup` render block.
