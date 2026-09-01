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
"""
Local chat-history / user platform API.

This controller makes eigent-theia self-contained: it serves the REST
surface that the agent panel and History sidebar expect (`/api/v1/user/*`,
`/api/v1/chat/histories*`, `/api/v1/chat/history/*`) using LOCAL persistence
under `~/.eigent/`. No external eigent/server Docker stack is required.

History records are projected from the already-persisted turn store that the
agent brain writes (`~/.eigent/turns/<chatId>/turn_*.json`), so the data shown
here is real conversation data, not fabricated.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Query

logger = logging.getLogger("chat_platform_controller")
router = APIRouter()


# --------------------------------------------------------------------------
# Persistence helpers (local, under ~/.eigent)
# --------------------------------------------------------------------------

def _home() -> Path:
    return Path.home() / ".eigent"


def _turns_root() -> Path:
    root = Path.home() / ".eigent" / "turns"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _task_key(chat_id: str) -> str:
    # chat dir names in the turn store already have / sanitized
    return str(chat_id).replace("/", "_")


def _iter_turn_files(chat_dir: Path) -> list[Path]:
    if not chat_dir.is_dir():
        return []
    return sorted(chat_dir.glob("turn_*.json"))


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("unreadable turn json (skipped): %s", path, exc_info=True)
        return None


# --------------------------------------------------------------------------
# History projection
# --------------------------------------------------------------------------

def _build_history_items() -> list[dict]:
    """
    Project HistoryTask records from the persisted turn store.

    Each chat directory under ~/.eigent/turns/ is treated as one task entry;
    its question comes from the first userMessage, timestamps from file mtime,
    status = 2 (done). Schema matches agent-ui/src/types/history.d.ts.
    """
    root = _turns_root()
    items: list[dict] = []
    if not root.exists():
        return items

    for chat_dir in sorted(root.iterdir()):
        if not chat_dir.is_dir():
            continue
        chat_id = chat_dir.name.replace("_", "/")
        files = _iter_turn_files(chat_dir)
        if not files:
            continue

        question = ""
        created_at = None
        updated_at = None
        for p in files:
            data = _load_json(p) or {}
            um = data.get("userMessage") or {}
            q = (um.get("content") or "").strip() or data.get("queryId")
            if q and not question:
                question = q
            st = os.path.getmtime(p)
            iso = _iso(st)
            if created_at is None or iso < created_at:
                created_at = iso
            if updated_at is None or iso > updated_at:
                updated_at = iso

        items.append(
            {
                "id": len(items) + 1,
                "task_id": chat_id,
                "project_id": chat_id,
                "space_id": "default",
                "question": question or chat_id,
                "language": "",
                "model_platform": "",
                "model_type": "",
                "max_retries": 3,
                "project_name": chat_id,
                "summary": None,
                "tokens": 0,
                "status": 2,  # ChatStatus.done
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )

    # newest first
    items.sort(key=lambda t: (t.get("created_at") or ""), reverse=True)
    # assign stable sequential ids after sort
    for idx, t in enumerate(items, start=1):
        t["id"] = idx
    return items


def _iso(epoch: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _group_items(items: list[dict]) -> list[dict]:
    from collections import OrderedDict

    groups: "OrderedDict[str, dict]" = OrderedDict()
    for task in items:
        pid = task["project_id"]
        g = groups.setdefault(
            pid,
            {
                "project_id": pid,
                "space_id": task.get("space_id"),
                "project_name": task.get("project_name") or f"Project {pid}",
                "total_tokens": 0,
                "task_count": 0,
                "total_triggers": 0,
                "latest_task_date": task.get("created_at")
                or task.get("updated_at") or "",
                "last_prompt": task.get("question") or "",
                "tasks": [],
                "total_completed_tasks": 0,
                "total_ongoing_tasks": 0,
                "average_tokens_per_task": 0,
            },
        )
        g["tasks"].append(task)
        g["task_count"] += 1
        g["total_tokens"] += task.get("tokens") or 0
        td = task.get("created_at") or task.get("updated_at") or ""
        if td > (g["latest_task_date"] or ""):
            g["latest_task_date"] = td
        if task.get("status") == 2:
            g["total_completed_tasks"] += 1
        elif task.get("status") == 1:
            g["total_ongoing_tasks"] += 1

    result = []
    for g in groups.values():
        g["tasks"] = sorted(
            g["tasks"],
            key=lambda t: t.get("created_at") or "",
            reverse=True,
        )
        g["average_tokens_per_task"] = (
            round(g["total_tokens"] / g["task_count"]) if g["task_count"] else 0
        )
        result.append(g)
    result.sort(key=lambda g: g.get("latest_task_date") or "", reverse=True)
    return result


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@router.post("/user/auto-login")
async def auto_login(payload: dict | None = None):
    """Local auto-login: return a fixed local identity + a session token."""
    _ = payload
    email = os.environ.get("EIGENT_LOCAL_EMAIL", "local@eigent.local")
    name = os.environ.get("EIGENT_LOCAL_NAME", "Local User")
    token = str(uuid.uuid4())
    return {
        "token": token,
        "email": email,
        "name": name,
        "user_id": "local",
        "tenant_id": "default",
    }


@router.get("/chat/histories")
async def list_histories(
    page: int = Query(1, ge=1),
    size: int = Query(200, ge=1, le=1000),
):
    items = _build_history_items()
    total = len(items)
    start = (page - 1) * size
    return {
        "items": items[start : start + size],
        "total": total,
        "page": page,
        "size": size,
    }


@router.get("/chat/histories/grouped")
async def grouped_histories(
    include_tasks: bool = Query(True),
    space_id: str | None = Query(None),
):
    items = _build_history_items()
    if space_id:
        items = [t for t in items if t.get("space_id") == space_id]
    projects = _group_items(items)
    if not include_tasks:
        for g in projects:
            g["tasks"] = []
    total_tokens = sum(g.get("total_tokens") or 0 for g in projects)
    total_tasks = sum(g.get("task_count") or 0 for g in projects)
    return {
        "projects": projects,
        "total_projects": len(projects),
        "total_tasks": total_tasks,
        "total_tokens": total_tokens,
    }


@router.get("/chat/histories/grouped/{project_id}")
async def grouped_history_project(project_id: str, include_tasks: bool = Query(True)):
    key = _task_key(project_id)
    chat_dir = _turns_root() / key
    if not chat_dir.is_dir():
        # empty project -> valid empty shape
        g = {
            "project_id": project_id,
            "space_id": "default",
            "project_name": project_id,
            "total_tokens": 0,
            "task_count": 0,
            "total_triggers": 0,
            "latest_task_date": "",
            "last_prompt": "",
            "tasks": [],
            "total_completed_tasks": 0,
            "total_ongoing_tasks": 0,
            "average_tokens_per_task": 0,
        }
        return g
    items = [t for t in _build_history_items() if t["project_id"] == project_id]
    groups = _group_items(items)
    g = groups[0] if groups else {}
    if not include_tasks:
        g["tasks"] = []
    return g


@router.get("/chat/history/{history_id}")
async def get_history(history_id: str):
    items = _build_history_items()
    # accept both numeric id and task_id / project_id
    for t in items:
        if (
            str(t.get("id")) == str(history_id)
            or t.get("task_id") == history_id
            or t.get("project_id") == history_id
        ):
            return t
    return {"error": "not_found", "message": f"history {history_id} not found"}


@router.delete("/chat/history/{history_id}")
async def delete_history(history_id: str):
    """
    Delete a history record. Locks are released by removing the persisted
    turns for that chatId so the record no longer projects.
    """
    key = _task_key(history_id)
    chat_dir = _turns_root() / key
    removed = 0
    if chat_dir.is_dir():
        for p in _iter_turn_files(chat_dir):
            try:
                p.unlink()
                removed += 1
            except OSError:
                logger.warning("could not delete turn file: %s", p)
        # remove empty chat dir
        try:
            chat_dir.rmdir()
        except OSError:
            pass
    return {"deleted": history_id, "removed_turns": removed}


@router.put("/chat/project/{project_id}/name")
async def rename_project(project_id: str, new_name: str = Query(...)):
    """
    Rename a project. The frontend sends `new_name` as a query parameter
    (`PUT /api/v1/chat/project/{projectId}/name?new_name=...`). We persist an
    override map so the new name survives restarts.
    """
    override_path = _home() / "project_names.json"
    data: dict = {}
    if override_path.exists():
        try:
            data = json.loads(override_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[str(project_id)] = new_name
    override_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"project_id": project_id, "project_name": new_name}
