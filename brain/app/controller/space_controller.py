# ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========
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
# ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========
"""
Local Spaces / Projects API — folder == project model.

Product model: "a project is basically a folder; any open folder in the editor
is a project and that project owns its conversations." Each open folder is a
distinct, PATH-STABLE Space (`folder_<sha256(root)>`), so re-opening the same
folder always yields the same Space id and therefore the SAME conversation list
— no cross-folder leakage and no per-open duplicates. A conversation is bound to
its folder when the client creates it in that folder Space
(`POST /spaces/{spaceId}/projects`); reads only surface conversations that
actually exist on disk.

Scoping (`_history_items_for_space`):
- Folder Space  → ONLY the conversations bound to that folder. A chat started in
  folder A never appears under folder B.
- Legacy/personal Space (`legacy_<user>`) → every on-device conversation
  (the catch-all "Local History").

This restores the behavior that regressed when the standalone migration dropped
the Spaces surface from the chat-platform controller (the History panel drives
off `/api/v1/spaces*`, not `/api/v1/chat/histories`). Response shapes match
`agent-ui/src/service/spaceApi.ts` (`ServerSpace`, `ServerProject`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Response

from app.controller.chat_platform_controller import (
    _build_history_items,
    _home,
    _is_personal_space_id,
    _local_space_id,
    _turns_root,
    _iso,
)

logger = logging.getLogger("space_controller")
router = APIRouter()

_LEGACY_SOURCE_TYPE = "legacy"
_FOLDER_SPACES_FILE = "folder_spaces.json"
_FOLDER_PREFIX = "folder_"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# Space payloads
# --------------------------------------------------------------------------

def _legacy_space_payload() -> dict:
    """Canonical on-device legacy/personal Space (the catch-all)."""
    now = _iso(os.path.getmtime(_turns_root())) if _turns_root().exists() else None
    return {
        "id": _local_space_id(),  # e.g. legacy_local
        "user_id": "local",
        "name": "Local History",
        "description": "Conversations stored on this device",
        "source_type": _LEGACY_SOURCE_TYPE,
        "root_path": str(_home()),
        "root_fingerprint": None,
        "status": "active",
        "schema_version": 1,
        "metadata": {"legacy": True},
        "created_at": now,
        "updated_at": now,
    }


def _project_payload_from_history_item(item: dict, space_id: str | None = None) -> dict:
    """Map a projected history/turn item onto the ServerProject schema."""
    return {
        "id": item.get("task_id") or item.get("project_id"),
        "user_id": "local",
        "space_id": space_id or _local_space_id(),
        "name": item.get("question") or item.get("project_name") or item.get("task_id"),
        "description": None,
        "mode": None,
        "status": "active",
        "workdir_mode": None,
        "metadata": None,
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }


# --------------------------------------------------------------------------
# Folder registry (folder_spaces.json)
# --------------------------------------------------------------------------

def _folder_registry_path() -> Path:
    return _home() / _FOLDER_SPACES_FILE


def _load_folder_registry() -> dict:
    p = _folder_registry_path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            logger.warning("unreadable folder-spaces registry: %s", p, exc_info=True)
    return {}


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _save_folder_registry(reg: dict) -> None:
    _atomic_write_json(_folder_registry_path(), reg)


def _norm_root(root: str | None) -> str | None:
    if not root:
        return None
    root = root.strip()
    if not root:
        return None
    root = os.path.expanduser(root)
    return os.path.normpath(root)


def _folder_space_id(root: str) -> str:
    digest = hashlib.sha256(root.encode("utf-8")).hexdigest()[:16]
    return f"{_FOLDER_PREFIX}{digest}"


def _folder_payload(root: str, reg_entry: dict) -> dict:
    now = _utcnow_iso()
    return {
        "id": reg_entry.get("id") or _folder_space_id(root),
        "user_id": "local",
        "name": reg_entry.get("name") or os.path.basename(root.rstrip("/\\")) or root,
        "description": "Conversations for this project folder",
        "source_type": "folder",
        "root_path": root,
        "root_fingerprint": None,
        "status": "active",
        "schema_version": 1,
        "metadata": {"folder": True},
        "created_at": reg_entry.get("created_at") or now,
        "updated_at": reg_entry.get("updated_at") or now,
    }


def _register_folder_space(root_path: str, name: str | None = None) -> dict:
    """Register (or refresh) a path-stable folder Space and return its payload."""
    root = _norm_root(root_path)
    if not root:
        raise HTTPException(status_code=400, detail="folder root_path is required")

    reg = _load_folder_registry()
    by_root = reg.setdefault("by_root", {})
    entry = by_root.get(root)
    if not entry:
        entry = {
            "id": _folder_space_id(root),
            "name": name or os.path.basename(root.rstrip("/\\")) or root,
            "root_path": root,
            "conversations": {},
            "created_at": _utcnow_iso(),
        }
    elif name:
        entry["name"] = name
    by_root[root] = entry
    _save_folder_registry(reg)
    return _folder_payload(root, entry)


def _folder_root_from_space_id(space_id: str) -> str | None:
    reg = _load_folder_registry()
    for r, e in (reg.get("by_root", {}) or {}).items():
        if e.get("id") == space_id:
            return r
    return None


def _folder_conversation_ids(root: str) -> set[str]:
    reg = _load_folder_registry()
    entry = ((reg.get("by_root", {}) or {}).get(root)) or {}
    return set((entry.get("conversations", {}) or {}).keys())


def _add_folder_conversation(root: str, project_id: str, name: str | None = None) -> None:
    reg = _load_folder_registry()
    by_root = reg.setdefault("by_root", {})
    entry = by_root.setdefault(
        root,
        {
            "id": _folder_space_id(root),
            "name": os.path.basename(root.rstrip("/\\")) or root,
            "root_path": root,
            "conversations": {},
        },
    )
    convs = entry.setdefault("conversations", {})
    if project_id not in convs:
        convs[project_id] = {"name": name or project_id, "added_at": _utcnow_iso()}
    elif name:
        convs[project_id]["name"] = name
    by_root[root] = entry
    _save_folder_registry(reg)


def _is_folder_space_id(space_id: str) -> bool:
    return bool(space_id and space_id.startswith(_FOLDER_PREFIX))


# --------------------------------------------------------------------------
# Space routes
# --------------------------------------------------------------------------

@router.get("/spaces")
async def list_spaces():
    """proxyFetchSpaces(): the legacy/personal Space plus every registered
    (opened) folder project-space."""
    spaces = [_legacy_space_payload()]
    reg = _load_folder_registry()
    for root, entry in (reg.get("by_root", {}) or {}).items():
        spaces.append(_folder_payload(root, entry))
    return spaces


@router.post("/spaces")
async def create_space(payload: dict | None = Body(default=None)):
    """proxyCreateSpace(): opening a folder (source_type='folder' + root_path)
    registers a path-stable folder project-space so the folder owns its own
    conversations. Blank/generic Spaces resolve to the single legacy container."""
    payload = payload or {}
    source_type = (payload.get("source_type") or "").lower()
    root_path = payload.get("root_path")
    if source_type == "folder":
        root = _norm_root(root_path)
        if root:
            return _register_folder_space(root, payload.get("name") or None)
    return _legacy_space_payload()


@router.get("/spaces/legacy")
async def fetch_legacy_space():
    return _legacy_space_payload()


@router.post("/spaces/legacy")
async def ensure_legacy_space(payload: dict | None = Body(default=None)):
    return _legacy_space_payload()


@router.get("/spaces/{space_id}")
async def fetch_space(space_id: str):
    if _is_folder_space_id(space_id):
        root = _folder_root_from_space_id(space_id)
        if root:
            reg = _load_folder_registry()
            entry = ((reg.get("by_root", {}) or {}).get(root)) or {}
            return _folder_payload(root, entry)
        raise HTTPException(status_code=404, detail=f"space {space_id} not found")
    payload = _legacy_space_payload()
    if space_id == payload["id"] or _is_personal_space_id(space_id):
        return payload
    raise HTTPException(status_code=404, detail=f"space {space_id} not found")


@router.patch("/spaces/{space_id}")
async def update_space(space_id: str, payload: dict = Body(default_factory=dict)):
    """Rename a folder Space (persisted in the registry). The legacy Space is
    fixed and returned unchanged."""
    if _is_folder_space_id(space_id):
        root = _folder_root_from_space_id(space_id)
        if not root:
            raise HTTPException(status_code=404, detail="space not found")
        name = payload.get("name")
        return _register_folder_space(root, name)
    return _legacy_space_payload()


@router.delete("/spaces/{space_id}")
async def delete_space(space_id: str) -> Response:
    """Unregister a folder Space (its conversations remain on disk and stay
    visible under the legacy catch-all). The legacy Space cannot be deleted."""
    if _is_folder_space_id(space_id):
        root = _folder_root_from_space_id(space_id)
        if root:
            reg = _load_folder_registry()
            (reg.get("by_root", {}) or {}).pop(root, None)
            _save_folder_registry(reg)
    return Response(status_code=204)


@router.post("/spaces/{space_id}/archive")
async def archive_space(space_id: str):
    return await fetch_space(space_id)


@router.post("/spaces/{space_id}/unarchive")
async def unarchive_space(space_id: str):
    return await fetch_space(space_id)


@router.post("/spaces/{space_id}/relocate")
async def relocate_space(space_id: str, payload: dict = Body(default_factory=dict)):
    return await fetch_space(space_id)


# --------------------------------------------------------------------------
# Project routes
# --------------------------------------------------------------------------

def _history_items_for_space(space_id: str, items: list[dict]) -> list[dict]:
    """Restrict projected history items to a specific Space.

    - Legacy/personal → every conversation on the device.
    - Folder Space → ONLY the conversations bound to that folder (existing on
      disk), never another folder's or another re-open's.
    """
    if _is_personal_space_id(space_id):
        return items
    if _is_folder_space_id(space_id):
        root = _folder_root_from_space_id(space_id)
        if not root:
            return []
        owned = _folder_conversation_ids(root)
        return [t for t in items if (t.get("task_id") or t.get("project_id")) in owned]
    return [t for t in items if t.get("space_id") == space_id]


@router.get("/spaces/{space_id}/projects")
async def list_space_projects(space_id: str):
    """proxyFetchSpaceProjects(): the conversations that belong to this Space,
    as projects. Folder Space → only that folder's conversations; legacy →
    every device conversation."""
    items = _build_history_items()
    scoped = _history_items_for_space(space_id, items) if items else items
    projects = []
    for t in scoped:
        sid = space_id if _is_folder_space_id(space_id) else _local_space_id()
        projects.append(_project_payload_from_history_item(t, space_id=sid))
    projects.sort(
        key=lambda p: (p.get("updated_at") or "") or (p.get("created_at") or ""),
        reverse=True,
    )
    return projects


@router.post("/spaces/{space_id}/projects")
async def create_space_project(space_id: str, payload: dict | None = Body(default=None)):
    """proxyCreateSpaceProject(): binds a freshly started conversation to a
    folder Space, so that folder's History lists conversations created while it
    was open."""
    payload = payload or {}
    project_id = payload.get("id") or payload.get("run_id")
    if _is_folder_space_id(space_id):
        root = _folder_root_from_space_id(space_id)
        if root and project_id:
            _add_folder_conversation(root, str(project_id), payload.get("name") or None)
    return {
        "id": project_id,
        "user_id": "local",
        "space_id": space_id,
        "name": payload.get("name") or "New Project",
        "description": None,
        "mode": None,
        "status": "active",
        "workdir_mode": None,
        "metadata": None,
        "created_at": None,
        "updated_at": None,
    }


@router.patch("/spaces/{space_id}/projects/{project_id}")
async def update_space_project(space_id: str, project_id: str, payload: dict = Body(default_factory=dict)):
    """Rename a project (persist the friendly name) and/or (re)bind it to a
    folder Space."""
    name = payload.get("name")
    if name:
        names_path = _home() / "project_names.json"
        names: dict = {}
        if names_path.exists():
            try:
                names = json.loads(names_path.read_text(encoding="utf-8"))
            except Exception:
                names = {}
        names[str(project_id)] = name
        _atomic_write_json(names_path, names)
    if _is_folder_space_id(space_id):
        root = _folder_root_from_space_id(space_id)
        if root:
            _add_folder_conversation(root, str(project_id), name)
    return {
        "id": project_id,
        "user_id": "local",
        "space_id": space_id,
        "name": name or project_id,
        "description": None,
        "mode": None,
        "status": payload.get("status") or "active",
        "workdir_mode": None,
        "metadata": None,
        "created_at": None,
        "updated_at": _utcnow_iso(),
    }


@router.post("/spaces/{space_id}/projects/{project_id}/promote")
async def promote_space_project(space_id: str, project_id: str):
    return await update_space_project(space_id, project_id, {"space_id": space_id})
