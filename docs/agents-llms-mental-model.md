<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Simon Ugorji
-->

# A mental model: LLMs, Agents, Tools, and Skills

A plain-language reference for how the pieces fit together — written against the
system you actually built (this agent product), so it's concrete, not abstract.

---

## The one-sentence idea

> An **LLM** is a text function. An **agent** is a loop that wraps the LLM so it
> can *act* and stay *grounded*. **Tools** are the agent's hands. **Skills** are
> reusable playbooks for a class of task.

Everything below expands that.

---

## 1. The LLM is just a text function

Strip everything away and a large language model is one stateless function:

```
(a pile of text)  ->  (the next chunk of text)
```

It has **no memory, no senses, no ability to act, no live data.** It can't open
a browser, read a file, or even remember your previous message on its own. What
it is extraordinarily good at is **language and reasoning**: given text, predict
the most sensible continuation.

So when you "chat with Claude on the web," the raw model isn't the thing that
searches the web or runs code — it just produces *words* (and, crucially,
*decisions* — see next).

**Consequence to remember:** when the model lacks a fact, it doesn't *know* it
lacks it — it just predicts the most plausible-looking text. That's why a weak
model will *invent* a PIN or a dummy API key instead of saying "I don't have
that." Hallucination isn't lying; it's the function doing exactly what it does
(predicting) with a gap in its input.

---

## 2. The extra trick: the model can *ask for actions*

Modern LLMs are trained so that, instead of only writing prose, they can emit a
**structured request**:

```
"call browser_visit_page(url='https://…')"
```

The model still isn't *doing* anything — it's emitting text that *means* "please
run this." Something **outside** the model has to actually run it and hand back
the result. That "something" is the agent.

---

## 3. The Agent = a loop around the LLM

An agent is **not a smarter model.** It's a loop plus scaffolding that turns the
text function into something that can act and stay grounded:

```
1. Build the prompt:  system instructions + history + your message + the list of
                      available tools
2. Ask the LLM:       it either answers, OR emits a tool call
3. If tool call:      the RUNTIME executes the real code, captures the result
4. Append the result to the conversation
5. Go back to step 2   ← repeat until the LLM produces a final answer
```

That loop is the whole game. The "human-like response" you get is the model's
language ability **plus** the loop letting it gather real information before it
answers.

Everything else an agent framework adds — memory, tool selection, permissions,
context management — is scaffolding to make that loop **grounded, safe, and
efficient**:

- **Memory / context** — the model is stateless, so the agent stores the
  conversation and relevant facts and re-feeds them each turn.
- **Tool selection (RAG)** — with dozens of tools, you don't show all of them
  every turn; you show the relevant ones (but expose a *whole* capability, not a
  fragment — a half-exposed toolset makes the model think it "can't do" the
  thing).
- **Grounding** — after something happens outside the model's view (e.g. a human
  takes over the browser), tell the model what happened, or it will *predict*
  what probably happened (and get it wrong).
- **Permissions / governance** — gate risky actions behind a human yes/no.

---

## 4. Tools = the model's hands

A tool is a plain function exposed to the model with three things:

- a **name** — `browser_click`
- a **description** — what it's for and when to use it (**the model reads this**
  to decide whether to reach for it)
- a **parameter schema** — typed arguments

The model **never runs the tool.** It emits `name + args`; the runtime runs the
actual code (browser, shell, file, an API) and returns the result as text. Tools
are the *only* way the model touches the real world.

Building one = "write a normal function, then describe it well enough that the
model knows when to use it." Description quality is not cosmetic — if the model
can't *find* or *understand* a tool, it behaves as if the tool doesn't exist.

---

## 5. Skills = packaged know-how

A tool is a single capability (a verb). A **skill** is a **reusable recipe** for
a *class of task*: instructions ("here's how to file an expense report"), often
bundling a few tool calls and domain judgement, that the agent **loads on
demand** instead of keeping in context all the time.

- Tools are **verbs**.
- A skill is a **short playbook**: which verbs, in what order, with what
  judgement, to accomplish something specific.

Loading skills on demand keeps the context small until a task actually needs
that know-how.

---

## 6. The stack, in one picture

```
LLM      the reasoner/writer. Text in, text (or a tool request) out.
         No memory, no hands.
   │
Agent    the loop + memory + orchestration that lets the LLM act and stay grounded.
   │
Tools    typed functions the LLM can request; the runtime executes them = the hands.
   │
Skills   loadable playbooks that compose tools + instructions for a class of task.
```

**Build order, bottom-up:** pick a model → wrap it in an act–observe loop
(agent) → give it tools (its hands) → package repeated workflows as skills.

---

## 7. How this maps to what you built

| Layer | In this product |
|---|---|
| **LLM** | The model you configure in the **Models** panel (OpenAI / Gemini / a local Ollama, …). Swappable — the reasoning engine only. |
| **Agent** | The brain's single-agent loop: build prompt → `astep` → run tool → feed result back → repeat. Plus memory, tool-RAG, governance, take-control grounding. |
| **Tools** | `browser_visit_page`, `browser_click`, file tools, terminal, the CDP browser, MCP connectors. When you said "log in to the sandbox," the model emitted `browser_visit_page`; the runtime drove Chromium; the page came back as text. |
| **Skills** | The skill toolkit (`list_skills` / `load_skill`) — packaged recipes the agent loads when a task matches. |

---

## 8. Why things go wrong (and what it teaches)

Real failures you saw, mapped back to the model:

- **"It claimed it entered a PIN it never entered."** During take-control the
  model was paused/blind — no observation of your actions — so it *predicted*
  plausible steps. Fix: **grounding** (tell it what happened) + rules against
  fabricating.
- **"It said it can't browse and opened my default browser."** The browser tool
  wasn't in its exposed set that turn, so — with no `browser_*` tools visible —
  it concluded it couldn't browse. Fix: **expose the whole capability** (tool-RAG
  atomic + always-on browser).
- **"It invented a dummy API key and flailed."** No credential was stored where
  it could reach it; lacking the fact, it predicted one. Fix: **store the
  credential** where the runtime injects it (a persistent browser profile, or an
  MCP server's `env`) — never rely on the model to *remember* a secret.

The pattern: **most "AI is dumb" moments are really "the loop didn't give the
model the right input."** Fix the scaffolding (tools, grounding, memory,
context), not just the model.

---

*Written as a companion to this project. Revisit whenever the layers blur
together — the trick is always to ask: "which layer is this — the reasoner, the
loop, the hands, or the playbook?"*
