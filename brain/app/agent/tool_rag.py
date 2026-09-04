# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
# Portions Copyright 2026 Simon Ugorji. All Rights Reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========

"""Local, embeddings-based tool selection ("tool RAG").

Function-calling is stateless: every tool's schema is re-sent on every LLM call.
With ~15 toolkits enabled plus a connected MCP catalog, that's easily 60-100+
tool schemas (tens of thousands of tokens) on EVERY step of EVERY turn. This
selector cuts that by exposing, per turn, only:

  * a small always-on CORE set (file / terminal / todo / memory / ask-human),
  * plus the top-K tools most semantically relevant to the user's message.

It reuses the same LOCAL MiniLM embeddings (chromadb's DefaultEmbeddingFunction)
already used by the memory layer — nothing leaves the machine, no extra heavy
deps. Degrades safely: if embeddings are unavailable or anything fails, it keeps
ALL tools (no capability loss, just no savings).
"""

import logging
import math
from typing import Any

from app.component.environment import env

logger = logging.getLogger("tool_rag")

# Toolkits whose tools are ALWAYS available (matched as a case-insensitive
# substring of the tool's tagged toolkit name). These are the primitives almost
# any task needs, so RAG never gates them.
# Toolkits ALWAYS exposed — the small primitives almost any task needs. Bigger,
# situational capabilities (browser, MCP connectors, web-deploy, …) are NOT here:
# tool-RAG attaches them WHEN the message calls for them (atomic-toolkit pulls the
# whole toolkit so it's never a dead-end fragment). That is the "agent knows when
# to attach a tool" mechanism — no static always-on, no toggle.
_CORE_TOOLKIT_MARKERS: tuple[str, ...] = (
    "human",
    "file",
    "terminal",
    "todo",
    "memory",
    "note",
    "message",
    # Reach the cached repo digest (understand_project) instead of blind-grepping
    # a project it already explored; and general search.
    "project context",
    # Surgical tree-sitter lookups (find_symbol / find_references / context_at)
    # — the precise companion to the broad repomix digest.
    "code query",
    "search",
)


def _core_toolkit_markers() -> tuple[str, ...]:
    return _CORE_TOOLKIT_MARKERS


def tool_rag_enabled() -> bool:
    """On by default; set UNDISCLOSED_TOOL_RAG=0 to disable."""
    return str(env("UNDISCLOSED_TOOL_RAG", "1")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _default_top_k() -> int:
    try:
        return max(1, int(env("UNDISCLOSED_TOOL_RAG_TOPK", "12")))
    except (TypeError, ValueError):
        return 12


def _min_score() -> float:
    """Minimum cosine similarity for a tool (and its toolkit) to be attached.
    Weak/no-intent messages (e.g. "hii") score below this, so ONLY the core
    tools are exposed instead of ballooning to whole toolkits. The agent can
    still pull anything in on demand via `load_capability`. Tune with
    UNDISCLOSED_TOOL_RAG_MIN_SCORE."""
    try:
        return float(env("UNDISCLOSED_TOOL_RAG_MIN_SCORE", "0.10"))
    except (TypeError, ValueError):
        return 0.10


def _max_per_toolkit() -> int:
    """Cap tools attached from a single toolkit. Atomic loading of a huge MCP
    toolkit (30 tools, ~40K tokens of schemas) is re-sent every step — so take
    only the most relevant N. Tune with UNDISCLOSED_TOOL_RAG_MAX_PER_TOOLKIT."""
    try:
        return max(1, int(env("UNDISCLOSED_TOOL_RAG_MAX_PER_TOOLKIT", "12")))
    except (TypeError, ValueError):
        return 12


def _toolkit_of(tool: Any) -> str:
    return str(getattr(tool, "_toolkit_name", "") or "")


def _tool_name(tool: Any) -> str:
    getter = getattr(tool, "get_function_name", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception:
            pass
    return str(getattr(tool, "__name__", "") or "")


def _tool_text(tool: Any) -> str:
    name = _tool_name(tool)
    desc = ""
    getter = getattr(tool, "get_function_description", None)
    if callable(getter):
        try:
            desc = str(getter() or "")
        except Exception:
            desc = ""
    return f"{name}. {desc}".strip()


def _is_core(tool: Any) -> bool:
    tk = _toolkit_of(tool).lower()
    return any(marker in tk for marker in _core_toolkit_markers())


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class ToolRAGSelector:
    """Selects a per-turn subset of tools: core + top-K by semantic relevance."""

    def __init__(self, tools: list[Any], top_k: int | None = None):
        self.top_k = top_k if top_k is not None else _default_top_k()
        self._by_name: dict[str, Any] = {}
        self.core_names: set[str] = set()
        self._rag_names: list[str] = []
        # Toolkit of each retrievable tool + its sibling names, so selection can
        # be ATOMIC: exposing a fragment of a toolkit (e.g. browser_visit_page
        # without browser_type/click) makes the model conclude it "can't browse"
        # and give up. When any tool of a toolkit is relevant, expose them all.
        self._toolkit_of_name: dict[str, str] = {}
        self._rag_names_by_toolkit: dict[str, list[str]] = {}
        for tool in tools:
            name = _tool_name(tool)
            if not name:
                continue
            self._by_name[name] = tool
            if _is_core(tool):
                self.core_names.add(name)
            else:
                self._rag_names.append(name)
                tk = _toolkit_of(tool)
                self._toolkit_of_name[name] = tk
                if tk:
                    self._rag_names_by_toolkit.setdefault(tk, []).append(name)
        self._embedder: Any | None = None
        self._rag_embs: list[list[float]] | None = None
        self._init_embeddings()

    def _init_embeddings(self) -> None:
        if not self._rag_names:
            return
        try:
            from chromadb.utils import embedding_functions

            self._embedder = embedding_functions.DefaultEmbeddingFunction()
            texts = [_tool_text(self._by_name[n]) for n in self._rag_names]
            self._rag_embs = list(self._embedder(texts))
            logger.info(
                "Tool-RAG ready: %d core, %d retrievable tools",
                len(self.core_names),
                len(self._rag_names),
            )
        except Exception:
            # No embeddings -> keep all tools (no filtering).
            logger.warning(
                "Tool-RAG embeddings unavailable; keeping all tools",
                exc_info=True,
            )
            self._embedder = None
            self._rag_embs = None

    @property
    def total_tools(self) -> int:
        return len(self._by_name)

    def all_tools(self) -> list[Any]:
        return list(self._by_name.values())

    def get(self, name: str) -> Any | None:
        return self._by_name.get(name)

    def select_names(self, query: str) -> set[str]:
        """Names to expose for this turn: core + top-K relevant (or all on
        failure)."""
        selected = set(self.core_names)
        if not self._rag_names:
            return selected
        if self._embedder is None or self._rag_embs is None:
            return selected | set(self._rag_names)
        q = (query or "").strip()
        if not q:
            return selected  # nothing to match on -> core only
        try:
            qv = list(self._embedder([q])[0])
            scored = sorted(
                (
                    (_cosine(qv, emb), name)
                    for emb, name in zip(self._rag_embs, self._rag_names)
                ),
                reverse=True,
            )
            threshold = _min_score()
            max_per = _max_per_toolkit()
            score_by_name = {name: s for s, name in scored}
            triggered: set[str] = set()
            for score, name in scored[: self.top_k]:
                # scored is sorted DESC — once below the relevance bar, stop, so
                # a no-intent message ("hii") exposes ONLY core instead of
                # ballooning to whole toolkits.
                if score < threshold:
                    break
                tk = self._toolkit_of_name.get(name)
                if tk:
                    triggered.add(tk)
                else:
                    selected.add(name)
            # Attach each triggered toolkit's MOST RELEVANT tools (capped), not
            # all — a full MCP toolkit is ~40K tokens of schemas re-sent per step.
            for tk in triggered:
                selected.update(self._top_names_for_toolkit(tk, score_by_name, max_per))
        except Exception:
            logger.warning(
                "Tool-RAG selection failed; keeping all tools", exc_info=True
            )
            return selected | set(self._rag_names)
        return selected

    def select_tools(self, query: str) -> list[Any]:
        names = self.select_names(query)
        return [self._by_name[n] for n in names if n in self._by_name]

    # --- on-demand capability loading (the `load_capability` meta-tool) ---

    def loadable_toolkits(self) -> dict[str, list[Any]]:
        """Non-core toolkits the agent can pull in on demand: name -> tools."""
        out: dict[str, list[Any]] = {}
        for name in self._rag_names:
            tk = self._toolkit_of_name.get(name)
            if tk:
                out.setdefault(tk, []).append(self._by_name[name])
        return out

    def capability_catalog(self) -> list[str]:
        """Loadable toolkit names, for the system prompt + meta-tool."""
        return sorted(self.loadable_toolkits().keys())

    def _score_names(self, query: str) -> dict[str, float]:
        """name -> cosine score for `query` ({} if no embedder/query)."""
        q = (query or "").strip()
        if self._embedder is None or self._rag_embs is None or not q:
            return {}
        try:
            qv = list(self._embedder([q])[0])
            return {
                name: _cosine(qv, emb)
                for emb, name in zip(self._rag_embs, self._rag_names)
            }
        except Exception:
            return {}

    def _top_names_for_toolkit(
        self, tk: str, score_by_name: dict[str, float], n: int
    ) -> list[str]:
        names = self._rag_names_by_toolkit.get(tk, [])
        if len(names) <= n:
            return list(names)
        return sorted(
            names, key=lambda x: score_by_name.get(x, 0.0), reverse=True
        )[:n]

    def tools_for_capabilities(
        self, names: list[str], query: str | None = None
    ) -> list[Any]:
        """Match requested capability names to toolkits; return their MOST
        RELEVANT tools (capped per toolkit, ranked by `query` when given) — a
        full MCP toolkit is ~40K tokens of schemas, far more than a task needs."""
        wanted = [str(n).strip().lower() for n in (names or []) if str(n).strip()]
        if not wanted:
            return []
        max_per = _max_per_toolkit()
        score_by_name = self._score_names(query) if query else {}
        result: list[Any] = []
        for tk, tools in self.loadable_toolkits().items():
            low = tk.lower()
            if not any(w in low or low in w for w in wanted):
                continue
            if len(tools) > max_per:
                if score_by_name:
                    tools = sorted(
                        tools,
                        key=lambda t: score_by_name.get(_tool_name(t), 0.0),
                        reverse=True,
                    )[:max_per]
                else:
                    tools = tools[:max_per]
            result.extend(tools)
        return result

    def capability_catalog_detailed(self) -> str:
        """Compact catalog for the LLM router: toolkit name + a few tool names
        as a purpose hint. Deliberately NOT full schemas — that would re-add the
        token bloat we're avoiding."""
        lines: list[str] = []
        for tk, tools in sorted(self.loadable_toolkits().items()):
            sample = ", ".join(_tool_name(t) for t in tools[:6])
            lines.append(f"- {tk}: {sample}")
        return "\n".join(lines)


async def route_capabilities(
    question: str, selector: "ToolRAGSelector", model_backend: Any
) -> list[str] | None:
    """Ask the LLM which capabilities (toolkits) a task needs, from a COMPACT
    catalog (names + sample tools, not schemas). Returns the chosen toolkit
    names, [] for none, or None on failure so the caller can fall back to
    embedding selection. Reuses the agent's own model (a throwaway, memory-
    isolated ChatAgent) — one small call in, a few names out."""
    q = (question or "").strip()
    catalog = selector.loadable_toolkits()
    if not q or not catalog:
        logger.info(
            "Capability router skipped (q=%s, catalog=%d, model=%s)",
            bool(q),
            len(catalog),
            model_backend is not None,
        )
        return []
    if model_backend is None:
        logger.warning("Capability router: no model_backend; using embeddings")
        return None
    try:
        from camel.agents import ChatAgent
        from camel.messages import BaseMessage

        router = ChatAgent(
            BaseMessage.make_assistant_message(
                role_name="ToolRouter",
                content=(
                    "You are a tool-capability router. Given a task and a list "
                    "of available capabilities, reply with ONLY the exact "
                    "capability names (as written) that the task will need, "
                    "comma-separated. If none are needed, reply exactly 'none'. "
                    "Do not explain."
                ),
            ),
            model=model_backend,
        )
        listing = selector.capability_catalog_detailed()
        response = await router.astep(
            f"Task:\n{q}\n\nAvailable capabilities:\n{listing}\n\n"
            "Which capabilities are needed?"
        )
        text = ""
        try:
            text = (response.msg.content or "").strip()
        except Exception:
            text = ""
        low = text.lower()
        if not text or low == "none":
            return []
        chosen = [tk for tk in catalog if tk.lower() in low]
        logger.info(
            "Capability router: %s -> %s", q[:60], chosen or "none"
        )
        return chosen
    except Exception:
        logger.warning(
            "Capability router failed; falling back to embeddings",
            exc_info=True,
        )
        return None


def _apply_desired(
    agent: Any, selector: ToolRAGSelector, desired: set[str]
) -> None:
    """Add/remove ONLY selector-managed tools so the live agent's tool set
    equals `desired` (core + selected). Anything a toolkit added dynamically —
    including tools loaded via load_capability — is left untouched."""
    current = set(getattr(agent, "tool_dict", {}) or {})
    managed = set(selector._by_name)
    for name in (current & managed) - desired:
        try:
            agent.remove_tool(name)
        except Exception:
            logger.debug("remove_tool failed for %s", name, exc_info=True)
    to_add = [
        selector.get(name)
        for name in desired - current
        if selector.get(name) is not None
    ]
    if to_add:
        agent.add_tools(to_add)


def reconcile_agent_tools(agent: Any, selector: ToolRAGSelector, query: str) -> None:
    """Embedding path: expose core + threshold-matched tools for `query`.
    Best-effort — failures leave tools as-is."""
    try:
        _apply_desired(agent, selector, selector.select_names(query))
    except Exception:
        logger.warning("Tool-RAG reconcile failed; leaving tools", exc_info=True)


async def reconcile_agent_tools_routed(
    agent: Any,
    selector: ToolRAGSelector,
    model_backend: Any,
    query: str,
) -> None:
    """Router path: let the LLM pick which capabilities the task needs (from a
    compact catalog), expose core + those. Falls back to the embedding path on
    any router failure. Best-effort — failures leave tools as-is."""
    try:
        routed = await route_capabilities(query, selector, model_backend)
        if routed is None:
            reconcile_agent_tools(agent, selector, query)  # embedding fallback
            return
        desired = set(selector.core_names)
        for tool in selector.tools_for_capabilities(routed, query):
            name = _tool_name(tool)
            if name:
                desired.add(name)
        _apply_desired(agent, selector, desired)
    except Exception:
        logger.warning(
            "Routed reconcile failed; leaving tools", exc_info=True
        )


# --------------------------------------------------------------------------
# Reusable factory helpers (shared by single-agent + workforce workers)
# --------------------------------------------------------------------------

_LOADABLE_CAPS_TEMPLATE = (
    "\n\n<loadable_capabilities>\n"
    "These tool capabilities are NOT loaded by default. The moment a task "
    "needs one, call load_capability([...]) with the name(s) below, then use "
    "the tools it returns:\n{items}\n</loadable_capabilities>"
)


def prepare_tool_rag(
    tools: list[Any],
    system_message: str,
) -> tuple[list[Any], str, "ToolRAGSelector | None"]:
    """Build a lean initial tool set for an agent + the loadable-capabilities
    prompt section. FAIL-SOFT: on any error (or when tool-RAG is disabled) it
    returns the tools + system_message unchanged and a None selector, so a
    caller can never end up WORSE than shipping every tool.

    Returns ``(initial_tools, system_message, selector)``.
    """
    if not tool_rag_enabled():
        return tools, system_message, None
    try:
        selector = ToolRAGSelector(tools)
        if not selector.total_tools:
            return tools, system_message, None
        initial_tools = selector.select_tools("")
        catalog = selector.capability_catalog()
        if catalog:
            items = "\n".join(f"- {name}" for name in catalog)
            system_message = system_message + _LOADABLE_CAPS_TEMPLATE.format(
                items=items
            )
        logger.info(
            "Tool-RAG: agent starts with %d core tools (of %d)",
            len(initial_tools),
            selector.total_tools,
        )
        return initial_tools, system_message, selector
    except Exception:
        logger.warning("prepare_tool_rag failed; using all tools", exc_info=True)
        return tools, system_message, None


def attach_load_capability(
    agent: Any,
    selector: "ToolRAGSelector | None",
    question: str,
) -> None:
    """Stash the selector on the agent and wire the ``load_capability`` meta-tool
    so the agent can pull whole toolkits in mid-task. Best-effort / no-op when
    there's no selector."""
    if selector is None:
        return
    agent._tool_rag_selector = selector
    try:
        from camel.toolkits import FunctionTool

        _selector = selector
        _agent_ref = agent

        def load_capability(capabilities: list[str]) -> str:
            """Attach additional tool capabilities (toolkits) when the current
            task needs them and they are not already available.

            Args:
                capabilities: Names of the capabilities to load, taken from the
                    <loadable_capabilities> list in your context
                    (e.g. ["Browser Toolkit"]).

            Returns:
                A short status describing what was loaded.
            """
            try:
                tools = _selector.tools_for_capabilities(capabilities, question)
                if not tools:
                    available = ", ".join(_selector.capability_catalog())
                    return (
                        f"No capability matched {capabilities}. "
                        f"Available: {available}"
                    )
                _agent_ref.add_tools(tools)
                return (
                    f"Loaded {capabilities}. Their tools are now available — "
                    "call them on your next step."
                )
            except Exception as exc:  # noqa: BLE001
                return f"Failed to load {capabilities}: {exc}"

        agent.add_tools([FunctionTool(load_capability)])
    except Exception:
        logger.warning("load_capability meta-tool wiring failed", exc_info=True)
