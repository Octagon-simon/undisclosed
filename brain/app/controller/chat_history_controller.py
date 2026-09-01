# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body

from app.component.environment import env

logger = logging.getLogger("chat_history_controller")
router = APIRouter()


@dataclass
class Message:
    id: str
    step: str | None
    content: str
    reasoning: str | None = None
    attaches: list[dict] = field(default_factory=list)
    fileList: list[dict] = field(default_factory=list)
    agent_name: str | None = None
    createdAt: str | None = None


@dataclass
class Turn:
    chatId: str
    queryId: str
    userMessage: dict | None = None
    otherMessages: list[dict] = field(default_factory=list)


def _turns_root() -> Path:
    root = Path.home() / ".eigent" / "turns"
    # Allow override for tests
    override = env("EIGENT_TURNS_ROOT", "").strip()
    if override:
        root = Path(override).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _turn_path(chat_id: str, query_id: str) -> Path:
    safe_chat = str(chat_id).replace("/", "_")
    safe_query = str(query_id).replace("/", "_")
    return _turns_root() / safe_chat / f"turn_{safe_query}.json"


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _load_turn(chat_id: str, query_id: str) -> Turn:
    p = _turn_path(chat_id, query_id)
    data = _read_json(p) or {}
    turn = Turn(chatId=chat_id, queryId=query_id)
    turn.userMessage = data.get("userMessage")
    turn.otherMessages = list(data.get("otherMessages") or [])
    return turn


def _save_turn(turn: Turn) -> None:
    p = _turn_path(turn.chatId, turn.queryId)
    _atomic_write_json(p, asdict(turn))


@router.post("/chat/{chat_id}/turns/{query_id}/messages")
async def post_message(
    chat_id: str,
    query_id: str,
    role: str = Body(..., embed=True),
    message: dict = Body(..., embed=True),
):
    """Append a message to a turn; upsert turn by (chatId, queryId)."""
    turn = _load_turn(chat_id, query_id)
    if role == "user":
        turn.userMessage = message
    else:
        # Prevent duplicates by id
        msg_id = message.get("id")
        if msg_id and any(m.get("id") == msg_id for m in turn.otherMessages):
            logger.debug("Duplicate assistant message ignored", extra={"chat_id": chat_id, "query_id": query_id, "id": msg_id})
        else:
            turn.otherMessages.append(message)
    _save_turn(turn)
    return asdict(turn)


@router.get("/chat/{chat_id}/turns")
async def list_turns(chat_id: str):
    """Return ordered array of turns for a chatId."""
    root = _turns_root() / str(chat_id).replace("/", "_")
    if not root.exists():
        return []
    items: list[dict] = []
    for p in sorted(root.glob("turn_*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            items.append(data)
        except Exception:
            logger.warning("Failed to read turn file", extra={"path": str(p)}, exc_info=True)
    # Preserve filename order (acts as insertion order). Could sort by userMessage.createdAt if available.
    return items


@router.get("/chat/{chat_id}/turns/{query_id}")
async def get_turn(chat_id: str, query_id: str):
    turn = _load_turn(chat_id, query_id)
    return asdict(turn)
