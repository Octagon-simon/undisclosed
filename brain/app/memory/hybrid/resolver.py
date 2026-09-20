# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
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

"""Project resolution: "continue the Mac app" -> a project id + confidence (§14).

A new thread must be connected to the recurring project it is about, so its
retrieval reads that project's memory instead of searching every prior
conversation equally (§3, §11). This module is the deterministic resolver for
that step. It is deliberately *not* a model classifier -- §28 warns against a
heavyweight LLM on every request -- and it is careful to be humble: §14 says a
low-confidence resolution should **broaden** retrieval, never silently force an
unrelated project onto the thread.

Signals, strongest first:

1. an explicit project id from the UI / conversation metadata (confidence 1.0);
2. a conversation already linked to a project -- the link is durable, so this
   survives a restart (confidence 0.9);
3. lexical overlap between the request and a project's name/description;
4. a single active project on the account (there is nothing else it could be).

The resolver never raises: an unreadable registry degrades to "unresolved",
which callers treat as "search broadly".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.memory.hybrid import text as T
from app.memory.hybrid.project import ProjectStore
from app.memory.hybrid.schema import Project

logger = logging.getLogger("memory.hybrid.resolver")

# Below this the caller should widen retrieval rather than trust the match.
# Deliberately low: a project *name* appearing in the request is a strong hint,
# partial keyword bleed is not (§14).
CONFIDENCE_FLOOR = 0.35


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class ProjectResolution:
    """The outcome of one resolution attempt (§14)."""

    project_id: str = ""
    space_id: str = ""
    confidence: float = 0.0
    reason: str = "none"
    candidates: list[tuple[str, float]] = field(default_factory=list)

    @property
    def confident(self) -> bool:
        """True only when a project was found with enough evidence to use it."""

        return bool(self.project_id) and self.confidence >= CONFIDENCE_FLOOR

    def to_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "space_id": self.space_id,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "candidates": self.candidates,
        }


def name_score(query: str, project: Project) -> float:
    """How strongly ``query`` names ``project``, 0..1 (§14)."""

    collapsed_query = T.collapse(query).lower()
    name = T.collapse(project.name or "")
    if not collapsed_query or not name:
        return 0.0
    name_lower = name.lower()
    # An exact phrase match pins the project even when the name is one long
    # token ("continue CheflyMenu"), which keyword overlap alone would miss if
    # the request carries extra words.
    if len(name_lower) >= 3 and name_lower in collapsed_query:
        return 0.95
    name_overlap = T.keyword_overlap(query, name)
    description_overlap = (
        T.keyword_overlap(query, project.description)
        if project.description
        else 0.0
    )
    entity_bonus = 0.1 if (T.entities(name) & T.entities(query)) else 0.0
    return min(
        1.0, 0.6 * name_overlap + 0.25 * description_overlap + entity_bonus
    )


def score_projects(
    query: str, projects: list[Project]
) -> list[tuple[Project, float]]:
    """Every project scored against ``query``, best first."""

    scored = [(project, name_score(query, project)) for project in projects]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored


def resolve(
    project_store: ProjectStore,
    user_key: str,
    *,
    query: str = "",
    conversation_id: str = "",
    explicit_project_id: str = "",
    explicit_space_id: str = "",
    link: bool = True,
    now: str = "",
    projects: list[Project] | None = None,
) -> ProjectResolution:
    """Resolve a request to a durable project (§14).

    ``projects`` lets a caller pass an already-discovered list (the engine reads
    it once for retrieval) so resolution does not re-walk the tree. When
    ``link`` is set and a resolution succeeds by name, the conversation is
    durably linked to the project so the next turn resolves in one hop.
    """

    try:
        discovered = (
            projects
            if projects is not None
            else project_store.discover(user_key)
        )
    except Exception:  # noqa: BLE001 - resolution must never break a turn
        logger.debug("hybrid: project discovery failed", exc_info=True)
        discovered = []

    by_id = {project.id: project for project in discovered}
    when = now or _utc_now()

    # 1. Explicit id -- the application knows exactly which project this is.
    if explicit_project_id:
        known = by_id.get(explicit_project_id)
        return ProjectResolution(
            project_id=explicit_project_id,
            space_id=explicit_space_id
            or (known.space_id if known is not None else ""),
            confidence=1.0,
            reason="explicit",
        )

    # 2. The conversation is already linked -- durable, survives restart (§20).
    if conversation_id:
        try:
            ref = project_store.project_for_conversation(
                user_key, conversation_id
            )
        except Exception:  # noqa: BLE001
            ref = None
        if ref is not None and ref.project_id:
            known = by_id.get(ref.project_id)
            return ProjectResolution(
                project_id=ref.project_id,
                space_id=ref.space_id
                or (known.space_id if known is not None else ""),
                confidence=0.9,
                reason="conversation_link",
            )

    if not (query or "").strip() or not discovered:
        return ProjectResolution(reason="no_query" if not query.strip() else "no_projects")

    scored = score_projects(query, discovered)
    candidates = [
        (project.id, round(score, 3)) for project, score in scored[:5]
    ]
    best, best_score = scored[0]
    if best_score >= CONFIDENCE_FLOOR:
        if link and conversation_id:
            project_store.link_conversation(
                user_key,
                conversation_id=conversation_id,
                project_id=best.id,
                space_id=best.space_id,
                now=when,
            )
        return ProjectResolution(
            project_id=best.id,
            space_id=best.space_id,
            confidence=best_score,
            reason="name_match",
            candidates=candidates,
        )

    # Low confidence: report the near-misses but force nothing, so the caller
    # broadens retrieval instead (§14).
    if best_score > 0:
        return ProjectResolution(
            confidence=best_score,
            reason="low_confidence",
            candidates=candidates,
        )

    # 3. Nothing named the project, but there is only one it could be.
    active = [project for project in discovered if project.status == "active"]
    if len(active) == 1:
        only = active[0]
        return ProjectResolution(
            project_id=only.id,
            space_id=only.space_id,
            confidence=CONFIDENCE_FLOOR,
            reason="only_active_project",
        )
    return ProjectResolution(reason="none")
