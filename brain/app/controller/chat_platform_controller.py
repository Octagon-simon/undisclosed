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
under `~/.undisclosed/`. No external eigent/server Docker stack is required.

History records are projected from the already-persisted turn store that the
agent brain writes (`~/.undisclosed/turns/<chatId>/turn_*.json`), so the data shown
here is real conversation data, not fabricated.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from enum import IntEnum
from fastapi import APIRouter, Body, Query, HTTPException, Response
from pydantic import BaseModel, Field, AliasChoices, field_validator

logger = logging.getLogger("chat_platform_controller")
router = APIRouter()


# --------------------------------------------------------------------------
# Persistence helpers (local, under ~/.undisclosed)
# --------------------------------------------------------------------------

def _home() -> Path:
    return Path.home() / ".undisclosed"


def _turns_root() -> Path:
    root = Path.home() / ".undisclosed" / "turns"
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
# Local space scoping
# --------------------------------------------------------------------------
# eigent-theia is a single-tenant, on-device brain: every persisted turn
# belongs to one local/personal scope. The agent UI derives its *active space
# id* from the local user's "legacy space" (`legacy_<userId>`; userId defaults
# to `local` => `legacy_local`) and then queries the grouped-history endpoint
# with that id. Persisted turns are not tagged with a space id, so we must
# expose them under whichever local/personal scope the UI is viewing rather
# than hard-matching a made-up id (previously `"default"`) and returning
# nothing (the "No conversations yet" symptom).

_DEFAULT_LOCAL_USER_ID = "local"


def _local_space_id() -> str:
    """Canonical personal-space id that history records are served under."""
    user = os.environ.get("EIGENT_LOCAL_USER_ID", "") or _DEFAULT_LOCAL_USER_ID
    return f"legacy_{user}"


def _is_personal_space_id(req: str | None) -> bool:
    """True when `req` refers to this brain's single local/personal scope."""
    if not req:
        return True
    norm = (req or "").strip().lower()
    if norm in {"default", "local"}:
        return True
    if norm == _local_space_id().lower():
        return True
    # Any legacy/personal derivation still maps to this one-tenant brain.
    if norm.startswith("legacy_") or norm.startswith("personal_"):
        return True
    return False


# --------------------------------------------------------------------------
# History projection
# --------------------------------------------------------------------------

def _build_history_items() -> list[dict]:
    """
    Project HistoryTask records from the persisted turn store.

    Each chat directory under ~/.undisclosed/turns/ is treated as one task entry;
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
                "space_id": _local_space_id(),
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
    if space_id and not _is_personal_space_id(space_id):
        # The UI is viewing a specific remote space. This on-device brain only
        # owns the personal space, so only records tagged exactly for that
        # requested space are relevant (there normally are none locally).
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
            "space_id": _local_space_id(),
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


@router.post("/chat/history")
async def create_history(data: dict = Body(...)):
    from datetime import datetime
    project_id = data.get("project_id") or data.get("task_id")
    project_name = data.get("project_name") or data.get("question")
    if project_id and project_name:
        await rename_project(project_id, project_name)

    now_iso = datetime.now().isoformat()
    return {
        "id": 1,
        "task_id": data.get("task_id") or project_id,
        "project_id": project_id,
        "run_id": data.get("run_id") or data.get("task_id") or project_id,
        "space_id": data.get("space_id") or _local_space_id(),
        "question": data.get("question") or "",
        "project_name": project_name,
        "status": data.get("status", 2),
        "tokens": data.get("tokens", 0),
        "summary": data.get("summary"),
        "created_at": now_iso,
        "updated_at": now_iso,
    }


@router.put("/chat/history/{history_id}")
async def update_history(history_id: str, data: dict = Body(...)):
    project_name = data.get("project_name")
    if project_name:
        await rename_project(history_id, project_name)

    return {
        "id": history_id,
        "task_id": history_id,
        "project_id": history_id,
        "project_name": project_name,
        **data
    }


@router.get("/server/capabilities")
async def get_server_capabilities():
    return {
        "features": {
            "connector_gateway": {
                "enabled": False,
                "provider": None,
                "reason": "standalone"
            }
        }
    }


# --------------------------------------------------------------------------
# Providers Endpoint Group
# --------------------------------------------------------------------------

class VaildStatus(IntEnum):
    not_valid = 1
    is_valid = 2


class ProviderIn(BaseModel):
    provider_name: str
    model_type: str
    api_key: str
    endpoint_url: str = ""
    encrypted_config: dict | None = None
    is_valid: VaildStatus = Field(
        default=VaildStatus.not_valid,
        validation_alias=AliasChoices("is_valid", "is_vaild"),
    )
    prefer: bool = False

    @field_validator("is_valid", mode="before")
    @classmethod
    def normalize_is_valid(cls, value):
        if isinstance(value, bool):
            return VaildStatus.is_valid if value else VaildStatus.not_valid
        return value


class ProviderPreferIn(BaseModel):
    provider_id: int


def _providers_file() -> Path:
    return _home() / "providers.json"


def _load_providers() -> list[dict]:
    p_file = _providers_file()
    if not p_file.exists():
        return []
    try:
        return json.loads(p_file.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Unreadable providers JSON: %s", p_file, exc_info=True)
        return []


def _save_providers(providers: list[dict]) -> None:
    p_file = _providers_file()
    try:
        p_file.write_text(json.dumps(providers, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logger.error("Failed to save providers JSON: %s", p_file, exc_info=True)


@router.get("/providers")
async def get_providers(
    keyword: str | None = None,
    prefer: bool | None = None,
):
    providers = _load_providers()
    filtered = []
    for p in providers:
        if keyword and keyword.lower() not in p.get("provider_name", "").lower():
            continue
        if prefer is not None and p.get("prefer") != prefer:
            continue
        filtered.append(p)
    return filtered


@router.get("/provider")
async def get_provider(id: int):
    providers = _load_providers()
    for p in providers:
        if p.get("id") == id:
            return p
    raise HTTPException(status_code=404, detail="Provider not found")


@router.post("/provider")
async def create_provider(data: ProviderIn):
    providers = _load_providers()
    new_id = max([p.get("id", 0) for p in providers] or [0]) + 1
    new_provider = {
        "id": new_id,
        "user_id": "local",
        "provider_name": data.provider_name,
        "model_type": data.model_type,
        "api_key": data.api_key,
        "endpoint_url": data.endpoint_url,
        "encrypted_config": data.encrypted_config,
        "prefer": data.prefer,
        "is_valid": int(data.is_valid),
    }
    providers.append(new_provider)
    _save_providers(providers)
    return new_provider


@router.put("/provider/{id}")
async def update_provider(id: int, data: ProviderIn):
    providers = _load_providers()
    for p in providers:
        if p.get("id") == id:
            p["provider_name"] = data.provider_name
            p["model_type"] = data.model_type
            p["api_key"] = data.api_key
            p["endpoint_url"] = data.endpoint_url
            p["encrypted_config"] = data.encrypted_config
            p["prefer"] = data.prefer
            p["is_valid"] = int(data.is_valid)
            _save_providers(providers)
            return p
    raise HTTPException(status_code=404, detail="Provider not found")


@router.delete("/provider/{id}")
async def delete_provider(id: int):
    providers = _load_providers()
    initial_len = len(providers)
    providers = [p for p in providers if p.get("id") != id]
    if len(providers) == initial_len:
        raise HTTPException(status_code=404, detail="Provider not found")
    _save_providers(providers)
    return Response(status_code=204)


@router.post("/provider/prefer")
async def set_provider_prefer(data: ProviderPreferIn):
    providers = _load_providers()
    success = False
    for p in providers:
        if p.get("id") == data.provider_id:
            p["prefer"] = True
            success = True
        else:
            p["prefer"] = False
    if not success:
        raise HTTPException(status_code=404, detail="Provider not found")
    _save_providers(providers)
    return {"success": True}


# --------------------------------------------------------------------------
# Configs Endpoint Group
# --------------------------------------------------------------------------

class ConfigIn(BaseModel):
    config_name: str
    config_value: str
    config_group: str


def _configs_file() -> Path:
    return _home() / "configs.json"


def _load_configs() -> list[dict]:
    c_file = _configs_file()
    if not c_file.exists():
        return []
    try:
        return json.loads(c_file.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Unreadable configs JSON: %s", c_file, exc_info=True)
        return []


def _save_configs(configs: list[dict]) -> None:
    c_file = _configs_file()
    try:
        c_file.write_text(json.dumps(configs, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logger.error("Failed to save configs JSON: %s", c_file, exc_info=True)


@router.get("/configs")
async def list_configs(
    config_group: str | None = None,
):
    configs = _load_configs()
    if config_group:
        return [c for c in configs if c.get("config_group") == config_group]
    return configs


@router.get("/configs/{config_id}")
async def get_config(config_id: int):
    configs = _load_configs()
    for c in configs:
        if c.get("id") == config_id:
            return c
    raise HTTPException(status_code=404, detail="Configuration not found")


@router.post("/configs")
async def create_config(data: ConfigIn):
    configs = _load_configs()
    new_id = max([c.get("id", 0) for c in configs] or [0]) + 1
    new_config = {
        "id": new_id,
        "user_id": "local",
        "config_name": data.config_name,
        "config_value": data.config_value,
        "config_group": data.config_group,
    }
    configs.append(new_config)
    _save_configs(configs)
    return new_config


@router.put("/configs/{config_id}")
async def update_config(config_id: int, data: ConfigIn):
    configs = _load_configs()
    for c in configs:
        if c.get("id") == config_id:
            c["config_name"] = data.config_name
            c["config_value"] = data.config_value
            c["config_group"] = data.config_group
            _save_configs(configs)
            return c
    raise HTTPException(status_code=404, detail="Configuration not found")


@router.delete("/configs/{config_id}")
async def delete_config(config_id: int):
    configs = _load_configs()
    initial_len = len(configs)
    configs = [c for c in configs if c.get("id") != config_id]
    if len(configs) == initial_len:
        raise HTTPException(status_code=404, detail="Configuration not found")
    _save_configs(configs)
    return Response(status_code=204)


@router.get("/config/info")
async def get_config_info(show_all: bool = False):
    return {
        "Slack": {
            "env_vars": ["SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "SLACK_APP_TOKEN"],
            "toolkit": "slack_toolkit",
            "trigger": "slack_trigger",
        },
        "Lark": {
            "env_vars": ["LARK_APP_ID", "LARK_APP_SECRET"],
            "toolkit": "lark_toolkit",
        },
        "Notion": {
            "env_vars": ["MCP_REMOTE_CONFIG_DIR"],
            "toolkit": "notion_mcp_toolkit",
        },
        "X(Twitter)": {
            "env_vars": [
                "TWITTER_CONSUMER_KEY",
                "TWITTER_CONSUMER_SECRET",
                "TWITTER_ACCESS_TOKEN",
                "TWITTER_ACCESS_TOKEN_SECRET",
            ],
            "toolkit": "twitter_toolkit",
        },
        "WhatsApp": {
            "env_vars": ["WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID"],
            "toolkit": "whatsapp_toolkit",
        },
        "LinkedIn": {
            "env_vars": [
                "LINKEDIN_CLIENT_ID",
                "LINKEDIN_CLIENT_SECRET",
                "LINKEDIN_ACCESS_TOKEN",
                "LINKEDIN_REFRESH_TOKEN",
            ],
            "toolkit": "linkedin_toolkit",
        },
        "Reddit": {
            "env_vars": [
                "REDDIT_CLIENT_ID",
                "REDDIT_CLIENT_SECRET",
                "REDDIT_USER_AGENT",
            ],
            "toolkit": "reddit_toolkit",
        },
        "Search": {
            "env_vars": ["GOOGLE_API_KEY", "SEARCH_ENGINE_ID", "EXA_API_KEY"],
            "toolkit": "search_toolkit",
        },
        "Audio Analysis": {
            "env_vars": [],
            "toolkit": "audio_analysis_toolkit",
        },
        "Code Execution": {
            "env_vars": [],
            "toolkit": "code_execution_toolkit",
        },
        "Craw4ai": {
            "env_vars": [],
            "toolkit": "craw4ai_toolkit",
        },
        "Dalle": {
            "env_vars": [],
            "toolkit": "dalle_toolkit",
        },
        "Edgeone Pages MCP": {
            "env_vars": [],
            "toolkit": "edgeone_pages_mcp_toolkit",
        },
        "Excel": {
            "env_vars": [],
            "toolkit": "excel_toolkit",
        },
        "File Write": {
            "env_vars": [],
            "toolkit": "file_write_toolkit",
        },
        "Github": {
            "env_vars": ["GITHUB_TOKEN"],
            "toolkit": "github_toolkit",
        },
        "Google Calendar": {
            "env_vars": [
                "GOOGLE_CLIENT_ID",
                "GOOGLE_CLIENT_SECRET",
                "GOOGLE_REFRESH_TOKEN",
            ],
            "toolkit": "google_calendar_toolkit",
        },
        "Google Drive MCP": {
            "env_vars": [],
            "toolkit": "google_drive_mcp_toolkit",
        },
        "Google Gmail": {
            "env_vars": [
                "GOOGLE_CLIENT_ID",
                "GOOGLE_CLIENT_SECRET",
                "GOOGLE_REFRESH_TOKEN",
                "GMAIL_GOOGLE_CLIENT_ID",
                "GMAIL_GOOGLE_CLIENT_SECRET",
                "GMAIL_GOOGLE_REFRESH_TOKEN",
            ],
            "toolkit": "google_gmail_native_toolkit",
        },
        "Image Analysis": {
            "env_vars": [],
            "toolkit": "image_analysis_toolkit",
        },
        "MCP Search": {
            "env_vars": [],
            "toolkit": "mcp_search_toolkit",
        },
        "PPTX": {
            "env_vars": [],
            "toolkit": "pptx_toolkit",
        },
        "RAG": {
            "env_vars": ["OPENAI_API_KEY"],
            "toolkit": "rag_toolkit",
        },
    }


# --------------------------------------------------------------------------
# Sharing and Key Endpoints
# --------------------------------------------------------------------------

@router.get("/user/key")
async def get_user_key():
    return {
        "key": "local-key",
    }


@router.get("/chat/share/info/{token}")
async def get_share_info(token: str):
    return {
        "chat_id": "local",
        "share_token": token,
    }


@router.post("/chat/share")
async def create_share():
    return {
        "share_token": "local-token",
    }


# --------------------------------------------------------------------------
# Remote Sub-Agents Endpoints
# --------------------------------------------------------------------------

class RemoteSubAgentProviderIn(BaseModel):
    provider_name: str
    model_type: str
    api_key: str
    endpoint_url: str = ""
    encrypted_config: dict | None = None
    enabled: bool = True


def _remote_sub_agents_file() -> Path:
    return _home() / "remote_sub_agents.json"


def _load_remote_sub_agents() -> list[dict]:
    f = _remote_sub_agents_file()
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Unreadable remote sub agents JSON: %s", f, exc_info=True)
        return []


def _save_remote_sub_agents(items: list[dict]) -> None:
    f = _remote_sub_agents_file()
    try:
        f.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logger.error("Failed to save remote sub agents JSON: %s", f, exc_info=True)


@router.get("/remote-sub-agent-providers")
async def list_remote_sub_agent_providers(
    provider_name: str | None = None,
):
    providers = _load_remote_sub_agents()
    if provider_name:
        return [p for p in providers if p.get("provider_name") == provider_name]
    return providers


@router.post("/remote-sub-agent-providers")
async def create_remote_sub_agent_provider(data: RemoteSubAgentProviderIn):
    providers = _load_remote_sub_agents()
    new_id = max([p.get("id", 0) for p in providers] or [0]) + 1
    new_provider = {
        "id": new_id,
        "provider_name": data.provider_name,
        "model_type": data.model_type,
        "api_key": data.api_key,
        "endpoint_url": data.endpoint_url,
        "encrypted_config": data.encrypted_config,
        "enabled": data.enabled,
    }
    providers.append(new_provider)
    _save_remote_sub_agents(providers)
    return new_provider


@router.put("/remote-sub-agent-providers/{provider_id}")
async def update_remote_sub_agent_provider(provider_id: int, data: RemoteSubAgentProviderIn):
    providers = _load_remote_sub_agents()
    for p in providers:
        if p.get("id") == provider_id:
            p["provider_name"] = data.provider_name
            p["model_type"] = data.model_type
            p["api_key"] = data.api_key
            p["endpoint_url"] = data.endpoint_url
            p["encrypted_config"] = data.encrypted_config
            p["enabled"] = data.enabled
            _save_remote_sub_agents(providers)
            return p
    raise HTTPException(status_code=404, detail="Remote sub-agent provider not found")


@router.delete("/remote-sub-agent-providers/{provider_id}")
async def delete_remote_sub_agent_provider(provider_id: int):
    providers = _load_remote_sub_agents()
    initial_len = len(providers)
    providers = [p for p in providers if p.get("id") != provider_id]
    if len(providers) == initial_len:
        raise HTTPException(status_code=404, detail="Remote sub-agent provider not found")
    _save_remote_sub_agents(providers)
    return Response(status_code=204)
