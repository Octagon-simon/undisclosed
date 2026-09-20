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

"""Agent-facing semantic memory tools.

Lets the agent SAVE durable facts and RECALL them by meaning across
conversations, backed by ``app.memory.semantic_store`` (local chromadb). This is
the agent-driven side of the memory layer; relevant facts are also injected into
the durable context automatically (see MemoryService), so recall is opt-in.
"""

import logging

from camel.toolkits import FunctionTool

from app.agent.toolkit.abstract_toolkit import AbstractToolkit
from app.memory import LocalMemoryStore, hybrid, semantic_store
from app.memory.hybrid.storage import HybridStore
from app.memory.rolling_summary import RollingSummary
from app.service.task import Agents

logger = logging.getLogger("memory_toolkit")

# A "broad" recall query is one that asks about the conversation as a whole
# ("the plan", "what we decided", "continue", "where were we") rather than a
# narrow fact lookup. For these the cumulative summary IS the answer; a raw
# keyword scan would only return fragments.
_BROAD_QUERY_TERMS = (
    "plan",
    "decided",
    "discussed",
    "continue",
    "so far",
    "summary",
    "recap",
    "context",
    "remember",
    "earlier",
    "where were we",
    "what we",
    "status",
)


def _is_broad_query(query: str) -> bool:
    q = (query or "").lower().strip()
    if not q:
        return True
    return any(term in q for term in _BROAD_QUERY_TERMS)


class MemoryToolkit(AbstractToolkit):
    """`remember_fact` / `recall_facts` scoped to the current user+project."""

    agent_name: str = Agents.single_agent

    def __init__(
        self,
        api_task_id: str,
        user_key: str | None = None,
        space_id: str | None = None,
        agent_name: str | None = None,
        store: LocalMemoryStore | None = None,
    ) -> None:
        # api_task_id == project_id (matches the other Undisclosed toolkits).
        self.api_task_id = api_task_id
        self.user_key = user_key
        self.space_id = space_id
        self._store = store
        if agent_name is not None:
            self.agent_name = agent_name

    # ----- Rolling summary helpers -----

    def _store_or_default(self) -> LocalMemoryStore:
        return self._store or LocalMemoryStore()

    def _read_summary_text(self) -> str:
        """Rendered cumulative summary for this Project ("" when unavailable)."""
        if not self.user_key or not self.space_id:
            return ""
        try:
            text = self._store_or_default().read_project_summary(
                self.user_key, self.space_id, self.api_task_id
            )
        except Exception:  # noqa: BLE001 — best-effort
            return ""
        return (text or "").strip()

    def _read_summary(self) -> RollingSummary | None:
        if not self.user_key or not self.space_id:
            return None
        try:
            payload = self._store_or_default().read_project_summary_json(
                self.user_key, self.space_id, self.api_task_id
            )
        except Exception:  # noqa: BLE001
            return None
        return RollingSummary.from_dict(payload)

    def remember_fact(self, fact: str) -> str:
        """Save a durable fact worth recalling in future conversations.

        Call this PROACTIVELY — without being asked — whenever you learn
        something durable about the user or their project: their name or how they
        want to be addressed, their preferences (tools, style, stack), stable
        environment details, and key decisions or constraints. Do it as soon as
        you learn the fact. You do NOT need the user to say "remember"; use your
        judgment, the same way a thoughtful assistant would.

        Keep each fact concise and self-contained. Do NOT store transient state,
        routine step results, or things that won't matter next time. Avoid
        duplicates (identical facts are de-duplicated automatically).

        Args:
            fact (str): One concise, self-contained fact to remember.

        Returns:
            str: Confirmation message.
        """
        fact = (fact or "").strip()
        if not fact:
            return "Nothing to remember (empty fact)."
        semantic_store.remember(
            self.user_key,
            self.space_id,
            self.api_task_id,
            fact,
            source="agent",
        )
        return f"Remembered: {fact}"

    def recall_facts(self, query: str) -> str:
        """Recall previously remembered facts relevant to a query. Relevant facts
        are already injected into your context automatically, so only call this
        when you need to look up something more specific.

        Args:
            query (str): What you want to recall about.

        Returns:
            str: Matching facts, or a note that none were found.
        """
        facts = semantic_store.recall(
            self.user_key,
            self.space_id,
            self.api_task_id,
            query,
            k=5,
        )
        if not facts:
            return "No relevant remembered facts."
        return "\n".join(f"- {f}" for f in facts)

    def recall_conversation(self, query: str) -> str:
        """Retrieve earlier messages from THIS conversation that match a query.

        Use this ONLY for a FOLLOW-UP whose current message refers to or builds
        on something said earlier (e.g. "the value you computed", "that file",
        "as we discussed", "continue") that you no longer have in working
        memory. Do NOT call it for a self-contained new task or a first message
        — there is nothing earlier to recall and it just wastes a step. If you
        can act on the message as written, do the work instead.

        Args:
            query (str): Words or a short phrase describing what to find.

        Returns:
            str: The most relevant earlier messages, or a note that none
            matched.
        """
        import json
        from pathlib import Path

        # 1. Cumulative summary FIRST. A broad query ("the plan", "what we
        #    decided", "continue") is answered by the summary directly; the raw
        #    keyword scan below only returns fragments for those.
        summary_text = self._read_summary_text()
        if summary_text and _is_broad_query(query):
            return summary_text

        # 2. Narrow lookup: raw per-turn keyword scan.
        root = (
            Path.home()
            / ".undisclosed"
            / "turns"
            / str(self.api_task_id).replace("/", "_")
        )
        scored: list[tuple[int, str, str]] = []
        if root.is_dir():
            terms = [t for t in query.lower().split() if len(t) > 2]
            for p in sorted(root.glob("turn_*.json")):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                msgs: list[tuple[str, str]] = []
                um = data.get("userMessage") or {}
                if um.get("content"):
                    msgs.append(("User", str(um["content"])))
                for m in data.get("otherMessages") or []:
                    c = m.get("content")
                    if c:
                        msgs.append(("Assistant", str(c)))
                for who, text in msgs:
                    low = text.lower()
                    score = sum(low.count(t) for t in terms) if terms else 0
                    if score > 0:
                        scored.append((score, who, text))

        if not scored:
            # 3. Fall back to the cumulative summary before giving up, so a
            #    narrow query that still relates to prior work gets continuity.
            if summary_text:
                return summary_text
            if not root.is_dir():
                return "No earlier messages found for this conversation."
            return "No earlier messages matched that query."

        scored.sort(key=lambda x: x[0], reverse=True)
        out: list[str] = []
        for _score, who, text in scored[:5]:
            snippet = text.strip()
            if len(snippet) > 600:
                snippet = snippet[:599] + "…"
            out.append(f"[{who}] {snippet}")
        return "\n\n".join(out)

    def recall_turns(self, k: int = 5) -> str:
        """Return the last K structured turn digests (oldest to newest).

        Use when you need a compact, ordered view of what each prior turn asked
        and did — e.g. to reconstruct a multi-step plan — instead of raw text
        snippets.

        Args:
            k (int): How many recent turns to return (default 5).

        Returns:
            str: One line per turn, or a note that no summary exists yet.
        """
        summary = self._read_summary()
        if summary is None or not summary.turns:
            # Fall back to the rendered summary if only the .md exists.
            text = self._read_summary_text()
            return text or "No conversation summary is available yet."
        try:
            count = max(1, int(k))
        except (TypeError, ValueError):
            count = 5
        turns = summary.turns[-count:]
        lines: list[str] = []
        for turn in turns:
            line = f"[Turn {turn.n} · {turn.status}] User: {turn.user}"
            if turn.did:
                line += f"\n  Did: {turn.did}"
            if turn.files:
                line += f"\n  Files: {', '.join(turn.files)}"
            lines.append(line)
        return "\n".join(lines)

    def recall_history(self, query: str) -> str:
        """Recall earlier conversation by meaning and by exact detail.

        Hybrid retrieval over THIS conversation: semantic episode search +
        lexical search over the raw messages + active structured memory. Prefer
        this over ``recall_conversation`` when the user asks about a whole
        earlier topic/discussion ("how did we design the auth system") or an
        exact historical detail ("what port did we settle on", "what exact
        timeout"). It returns verbatim source messages when they exist, and says
        so plainly when nothing was found rather than inventing a detail.

        Args:
            query (str): What to recall about.

        Returns:
            str: Retrieved episodes, exact evidence, and active memory, or a
            note that nothing relevant was found.
        """
        query = (query or "").strip()
        if not query:
            return "Nothing to look up (empty query)."
        if not self.user_key or not self.space_id:
            return "No earlier history is available for this conversation."

        try:
            store = self._store_or_default()
            hybrid_store = HybridStore(store)
            events = hybrid.engine.load_events(
                store, self.user_key, self.space_id, self.api_task_id
            )
            if not events:
                return "No earlier messages found for this conversation."
            result, _recent = hybrid.engine.retrieve(
                hybrid_store,
                user_key=self.user_key,
                space_id=self.space_id,
                project_id=self.api_task_id,
                conversation_id=self.api_task_id,
                query=query,
                token_budget=4000,
                events=events,
            )
        except Exception:  # noqa: BLE001 — recall is best-effort
            logger.warning("recall_history failed", exc_info=True)
            return "Could not search earlier history right now."

        blocks: list[str] = []
        if result.episodes:
            lines = ["Relevant earlier episodes:"]
            lines.extend(f"- {item.text.strip()}" for item in result.episodes)
            blocks.append("\n".join(lines))
        if result.messages:
            lines = ["Exact evidence from earlier messages:"]
            lines.extend(f"- {item.text.strip()}" for item in result.messages)
            blocks.append("\n".join(lines))
        if result.active_memories:
            lines = ["Active memory:"]
            lines.extend(
                f"- {item.text.strip()}" for item in result.active_memories
            )
            if result.superseded_memories:
                lines.append("Superseded (historical, not current):")
                lines.extend(
                    f"- {item.text.strip()}"
                    for item in result.superseded_memories
                )
            blocks.append("\n".join(lines))

        if not blocks:
            return "No relevant earlier history was found for that query."
        return "\n\n".join(blocks)

    def get_tools(self) -> list[FunctionTool]:
        return [
            FunctionTool(self.remember_fact),
            FunctionTool(self.recall_facts),
            FunctionTool(self.recall_conversation),
            FunctionTool(self.recall_turns),
            FunctionTool(self.recall_history),
        ]

    @classmethod
    def toolkit_name(cls) -> str:
        return "Memory Toolkit"
