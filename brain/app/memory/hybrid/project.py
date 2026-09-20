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

"""Durable project / entity layer + conversation links (§3, §13, §14, §29).

``memory-cross-session-feature.md`` §3 argues cross-thread retrieval is only
reliable once conversations are grouped under a durable entity: a new thread
saying "continue the Mac app" should resolve to one project and read *that*
project's memory, rather than searching every prior conversation equally. This
module owns the two durable pieces that makes possible:

* a **user-level project registry** (``<user>/projects.json``) holding the
  fields the existing per-project ``project.json`` does not carry -- a
  ``description`` and an ``archived`` lifecycle -- and
* a **conversation -> project link** (``<user>/conversations.json``) so a
  thread can point at the project it belongs to.

Both live at the *user* root, next to :class:`~app.memory.hybrid.scope.GlobalMemoryStore`,
because a project spans threads and so cannot live under any one project dir
(§2). The registry is deliberately *additive*: :meth:`ProjectStore.discover`
unions it with a walk of the existing on-disk tree, reading each project's
authoritative name from the ``project.json`` already written by
``MemoryService``. A tree that predates this layer therefore still resolves
correctly, with no migration step (§29 "extend rather than duplicate").
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.memory.hybrid.schema import (
    PROJECT_STATUSES,
    ConversationRef,
    Project,
)
from app.memory.hybrid.scope import iter_user_projects
from app.memory.local_store import (
    LocalMemoryStore,
    read_json_file,
    update_json_file,
)

logger = logging.getLogger("memory.hybrid.project")

_REGISTRY = "projects.json"
_CONVERSATIONS = "conversations.json"


class ProjectStore:
    """The user-level registry of projects and their conversation links."""

    def __init__(self, store: LocalMemoryStore) -> None:
        self._store = store

    @property
    def base(self) -> LocalMemoryStore:
        return self._store

    def _path(self, user_key: str, name: str) -> Path:
        return self._store.user_path(user_key) / name

    # ----- Projects -----

    def read_projects(self, user_key: str) -> list[Project]:
        """Registered projects (registry only -- see :meth:`discover` for all)."""

        payload = read_json_file(self._path(user_key, _REGISTRY))
        rows = payload.get("projects") if isinstance(payload, dict) else None
        out: list[Project] = []
        for row in rows if isinstance(rows, list) else []:
            project = Project.from_dict(row)
            if project is not None:
                out.append(project)
        return out

    def get(self, user_key: str, project_id: str) -> Project | None:
        for project in self.read_projects(user_key):
            if project.id == project_id:
                return project
        return None

    def ensure(
        self,
        user_key: str,
        *,
        project_id: str,
        space_id: str = "",
        name: str = "",
        description: str = "",
        now: str = "",
    ) -> Project | None:
        """Get-or-create the registry entry for ``project_id``.

        Idempotent: the first call creates the record, later calls refresh the
        name/space/``updated_at`` while preserving ``created_at``, the existing
        description (unless a new one is supplied) and the ``status``. Never
        raises into the caller's turn -- a registry write failure logs and
        returns ``None``.
        """

        if not project_id:
            return None

        def _mutate(payload: object) -> dict[str, object]:
            rows = payload.get("projects") if isinstance(payload, dict) else None
            by_id: dict[str, Project] = {}
            for row in rows if isinstance(rows, list) else []:
                project = Project.from_dict(row)
                if project is not None:
                    by_id[project.id] = project
            current = by_id.get(project_id)
            by_id[project_id] = Project(
                id=project_id,
                user_id=user_key,
                name=(name or (current.name if current else "") or project_id),
                description=(
                    description or (current.description if current else "")
                ),
                status=(current.status if current else "active"),
                space_id=(space_id or (current.space_id if current else "")),
                created_at=(current.created_at if current else now),
                updated_at=now,
            )
            return {"projects": [p.to_dict() for p in by_id.values()]}

        try:
            updated = update_json_file(self._path(user_key, _REGISTRY), _mutate)
        except Exception:  # noqa: BLE001 - registry write is best-effort
            logger.debug("hybrid: project registry write failed", exc_info=True)
            return None
        rows = updated.get("projects") if isinstance(updated, dict) else None
        for row in rows if isinstance(rows, list) else []:
            project = Project.from_dict(row)
            if project is not None and project.id == project_id:
                return project
        return None

    def set_status(
        self,
        user_key: str,
        project_id: str,
        status: str,
        *,
        now: str = "",
    ) -> Project | None:
        """Move a project between ``active`` and ``archived`` (§3)."""

        if status not in PROJECT_STATUSES:
            return None
        existing = self.get(user_key, project_id)
        if existing is None:
            return None
        self.ensure(
            user_key,
            project_id=project_id,
            space_id=existing.space_id,
            name=existing.name,
            description=existing.description,
            now=now,
        )
        return self._force_status(user_key, project_id, status, now=now)

    def _force_status(
        self, user_key: str, project_id: str, status: str, *, now: str = ""
    ) -> Project | None:
        def _mutate(payload: object) -> dict[str, object]:
            rows = payload.get("projects") if isinstance(payload, dict) else None
            by_id: dict[str, Project] = {}
            for row in rows if isinstance(rows, list) else []:
                project = Project.from_dict(row)
                if project is not None:
                    by_id[project.id] = project
            current = by_id.get(project_id)
            if current is None:
                return {"projects": [p.to_dict() for p in by_id.values()]}
            by_id[project_id] = Project(
                **{**current.to_dict(), "status": status, "updated_at": now}
            )
            return {"projects": [p.to_dict() for p in by_id.values()]}

        updated = update_json_file(self._path(user_key, _REGISTRY), _mutate)
        rows = updated.get("projects") if isinstance(updated, dict) else None
        for row in rows if isinstance(rows, list) else []:
            project = Project.from_dict(row)
            if project is not None and project.id == project_id:
                return project
        return None

    def discover(self, user_key: str) -> list[Project]:
        """Every project the user's durable tree knows about (§14).

        The union of the registry and a walk of
        ``<user>/spaces/<s>/projects/<p>``. The walk contributes the
        authoritative ``name`` from each project's existing ``project.json``, so
        projects created before this layer existed are discoverable without a
        migration. The registry overlays ``description``/``status`` and supplies
        any project whose directory the walk could not read.
        """

        by_id: dict[str, Project] = {}
        try:
            found = iter_user_projects(self._store, user_key)
        except Exception:  # noqa: BLE001 - degrade to the registry
            logger.debug("hybrid: project walk failed", exc_info=True)
            found = []

        for space_id, project_id in found:
            name = ""
            try:
                record = self._store.read_project(user_key, space_id, project_id)
                name = (record.name or "") if record is not None else ""
            except Exception:  # noqa: BLE001 - one unreadable project
                name = ""
            by_id[project_id] = Project(
                id=project_id,
                user_id=user_key,
                name=name or project_id,
                space_id=space_id,
            )

        for project in self.read_projects(user_key):
            base = by_id.get(project.id)
            if base is None:
                by_id[project.id] = project
                continue
            by_id[project.id] = Project(
                id=project.id,
                user_id=project.user_id or user_key,
                name=project.name or base.name,
                description=project.description or base.description,
                status=project.status or base.status,
                space_id=project.space_id or base.space_id,
                created_at=project.created_at or base.created_at,
                updated_at=project.updated_at or base.updated_at,
            )
        return list(by_id.values())

    def active_projects(self, user_key: str) -> list[Project]:
        """Discovered projects whose status is ``active`` (§14)."""

        return [p for p in self.discover(user_key) if p.status == "active"]

    # ----- Conversation links -----

    def read_conversations(self, user_key: str) -> list[ConversationRef]:
        payload = read_json_file(self._path(user_key, _CONVERSATIONS))
        rows = payload.get("conversations") if isinstance(payload, dict) else None
        out: list[ConversationRef] = []
        for row in rows if isinstance(rows, list) else []:
            ref = ConversationRef.from_dict(row)
            if ref is not None:
                out.append(ref)
        return out

    def link_conversation(
        self,
        user_key: str,
        *,
        conversation_id: str,
        project_id: str,
        space_id: str = "",
        title: str = "",
        now: str = "",
    ) -> ConversationRef | None:
        """Point ``conversation_id`` at ``project_id`` (idempotent §3, §13)."""

        if not conversation_id or not project_id:
            return None

        def _mutate(payload: object) -> dict[str, object]:
            rows = (
                payload.get("conversations")
                if isinstance(payload, dict)
                else None
            )
            by_id: dict[str, ConversationRef] = {}
            for row in rows if isinstance(rows, list) else []:
                ref = ConversationRef.from_dict(row)
                if ref is not None:
                    by_id[ref.id] = ref
            current = by_id.get(conversation_id)
            by_id[conversation_id] = ConversationRef(
                id=conversation_id,
                user_id=user_key,
                project_id=project_id,
                space_id=space_id or (current.space_id if current else ""),
                title=title or (current.title if current else ""),
                created_at=(current.created_at if current else now),
                updated_at=now,
            )
            return {"conversations": [c.to_dict() for c in by_id.values()]}

        try:
            update_json_file(self._path(user_key, _CONVERSATIONS), _mutate)
        except Exception:  # noqa: BLE001 - link write is best-effort
            logger.debug("hybrid: conversation link failed", exc_info=True)
            return None
        return self.project_for_conversation(user_key, conversation_id)

    def project_for_conversation(
        self, user_key: str, conversation_id: str
    ) -> ConversationRef | None:
        for ref in self.read_conversations(user_key):
            if ref.id == conversation_id:
                return ref
        return None

    def conversations_for_project(
        self, user_key: str, project_id: str
    ) -> list[ConversationRef]:
        return [
            ref
            for ref in self.read_conversations(user_key)
            if ref.project_id == project_id
        ]
