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
from app.memory import semantic_store
from app.service.task import Agents

logger = logging.getLogger("memory_toolkit")


class MemoryToolkit(AbstractToolkit):
    """`remember_fact` / `recall_facts` scoped to the current user+project."""

    agent_name: str = Agents.single_agent

    def __init__(
        self,
        api_task_id: str,
        user_key: str | None = None,
        space_id: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        # api_task_id == project_id (matches the other Undisclosed toolkits).
        self.api_task_id = api_task_id
        self.user_key = user_key
        self.space_id = space_id
        if agent_name is not None:
            self.agent_name = agent_name

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

        root = (
            Path.home()
            / ".undisclosed"
            / "turns"
            / str(self.api_task_id).replace("/", "_")
        )
        if not root.is_dir():
            return "No earlier messages found for this conversation."
        terms = [t for t in query.lower().split() if len(t) > 2]
        scored: list[tuple[int, str, str]] = []
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
            return "No earlier messages matched that query."
        scored.sort(key=lambda x: x[0], reverse=True)
        out: list[str] = []
        for _score, who, text in scored[:5]:
            snippet = text.strip()
            if len(snippet) > 600:
                snippet = snippet[:599] + "…"
            out.append(f"[{who}] {snippet}")
        return "\n\n".join(out)

    def get_tools(self) -> list[FunctionTool]:
        return [
            FunctionTool(self.remember_fact),
            FunctionTool(self.recall_facts),
            FunctionTool(self.recall_conversation),
        ]

    @classmethod
    def toolkit_name(cls) -> str:
        return "Memory Toolkit"
