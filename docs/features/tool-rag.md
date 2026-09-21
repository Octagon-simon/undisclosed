# Tool-RAG: per-turn tool selection

**Problem.** Function calling is stateless: every tool's JSON schema is re-sent on
every LLM call. With ~15 toolkits enabled plus a connected MCP catalog, that is
60-100+ schemas (tens of thousands of tokens) on **every step of every turn**, and
providers bill it at 0% cache until prompt caching kick in.

**Solution.** `brain/app/agent/tool_rag.py` exposes, per turn, only a small
always-on core plus the tools that are actually relevant. It degrades to "all
tools" on any failure, so it can never make the agent *less* capable, only cheaper.

---

## How selection works

1. **Core set, always exposed** (`_CORE_TOOLKIT_MARKERS`): `human`, `file`,
   `terminal`, `todo`, `memory`, `note`, `message`, `skill`, `project context`
   (`understand_project`), `code query` (tree-sitter lookups), `search`.
   Bigger, situational capabilities (browser, MCP connectors, web-deploy) are NOT
   core; they are attached when the message calls for them.
2. **LLM router** (`route_capabilities`): per turn, the agent's own model (via a
   throwaway, memory-isolated `ChatAgent`) picks which toolkits the task needs
   from a **compact catalog** (toolkit name + a few sample tool names, *not*
   schemas). The main agent then gets the full schemas of only those toolkits plus
   core. An LLM can tell "hello" from "go to afriex and log in" where a raw
   embedding score cannot.
3. **Embedding fallback**: if the router fails, a local MiniLM cosine score
   decides. A relevance threshold (`UNDISCLOSED_TOOL_RAG_MIN_SCORE`, default 0.10,
   calibrated from real scores) gates attachment, so weak messages ("hii",
   ~0.06-0.09) expose core only.
4. **Atomic toolkits**: when any tool of a toolkit is relevant, the whole toolkit
   is exposed. This fixed a real bug where tool-RAG exposed
   `browser_visit_page` without `browser_click`, so the agent concluded it "can't
   browse" and gave up.
5. **Per-toolkit cap** (`UNDISCLOSED_TOOL_RAG_MAX_PER_TOOLKIT`, default 12): a
   30-tool MCP toolkit contributes its most relevant 12, ranked by query
   similarity, in both the embedding and router paths. A full MCP toolkit was
   ~40K tokens of schemas, re-sent every step.

## Mid-task needs: `load_capability`

Selection is per turn, so a need that only appears mid-task would be missed. The
`load_capability(capabilities)` meta-tool lets the agent attach a whole toolkit on
demand; CAMEL rebuilds tool schemas each iteration, so the new tools are usable on
the next step. The `<loadable_capabilities>` catalog (toolkit names only) is
injected into the system prompt, deliberately not full schemas (that would re-add
the bloat). Deferred toolkits (Browser, Screenshot) are constructed at this point,
so a reasoning turn never launches Chromium.

## What actually changed the numbers

The `[USAGE]` per-request log made this measurable:

- A task hit **60K input/step** because `load_capability(MCPToolkit)` dumped ~40K
  of Asana schemas while the agent made 14 near-duplicate calls. Fix: per-toolkit
  cap + a prompt rule to be economical with tool calls.
- `"hii"` sent **101 of 145** schemas (~50K tokens) because atomic-toolkit
  expansion over-fired on weak matches. Fix: the similarity threshold.
- The router replaced the blunt embedding *decision* while keeping the embedding
  path as fallback.

## Config

- `UNDISCLOSED_TOOL_RAG` (default on): `0` disables, keeping all tools.
- `UNDISCLOSED_TOOL_RAG_TOPK` (default 12)
- `UNDISCLOSED_TOOL_RAG_MIN_SCORE` (default 0.10)
- `UNDISCLOSED_TOOL_RAG_MAX_PER_TOOLKIT` (default 12)
- `UNDISCLOSED_TOOL_ROUTER` (default on): the LLM router path.

## Where it lives

- Selection + router + `load_capability`: `brain/app/agent/tool_rag.py`
- Built into the agent: `brain/app/agent/factory/single_agent.py`
- Reconciled per turn: `brain/app/service/single_agent_service.py`

## Key commits

`1f5e636` (cap huge MCP toolkits), `fdca2c4` (LLM router), `5982617` (similarity
threshold), `050cef9` (atomic toolkits + always-on browser), `3c9e931` (browser
retrievable again to cut input tokens).
