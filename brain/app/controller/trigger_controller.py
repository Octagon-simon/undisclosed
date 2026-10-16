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
"""Local Automations (triggers) API.

The editor's Automations panel (`agent-ui/src/components/Trigger/*`) and the
classic workspace page both talk to `/api/v1/trigger/*` and `/api/v1/execution/*`
via `service/triggerApi.ts`. In the standalone fork that surface never existed on
the local Brain (it lived in the upstream cloud `eigent/server`), so every call
404'd — the "returns 404 when I visit the automations screen" bug.

This controller implements that surface locally, single-user, persisted as JSON
under `~/.undisclosed/triggers/` (the same on-disk home the rest of the local
Brain uses for turns / spaces). Endpoint shapes match the TypeScript client:

  GET    /trigger/                        -> { items, total, page, size }
  GET    /trigger/{trigger_type}/config   -> { trigger_type, schema_ }
  GET    /trigger/{trigger_id}            -> Trigger
  POST   /trigger/                        -> Trigger
  PUT    /trigger/{trigger_id}            -> Trigger
  DELETE /trigger/{trigger_id}            -> 204
  POST   /trigger/{trigger_id}/activate   -> Trigger
  POST   /trigger/{trigger_id}/deactivate -> Trigger
  GET    /trigger/{trigger_id}/executions -> { items, total, page, size }
  PUT    /execution/{execution_id}        -> TriggerExecution
  POST   /execution/{execution_id}/retry  -> TriggerExecution
  WS     /execution/subscribe             -> execution_created/updated events

A tiny in-process scheduler fires active `schedule` triggers (5-field cron) and
broadcasts `execution_created` over the WS so the panel's task executor can run
them. Inbound `slack_trigger` automations are driven by
`app/service/slack_socket_listener.py` (Slack Socket Mode over an outbound
websocket, since the local Brain's loopback webhook URL is unreachable from
Slack's cloud); it calls `dispatch_slack_event` below. Generic `webhook`
triggers are still driven by the public inbound route. This is a local,
best-effort implementation, not the upstream cloud runtime.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)

from app.auth import BrainAuthContext, get_brain_auth_context
from app.component.environment import env

logger = logging.getLogger("trigger_controller")

router = APIRouter()
ws_router = APIRouter()
# Public, auth-free router for inbound webhooks. An external caller (Slack, a
# generic webhook source) can't present the Brain auth header, so these routes
# are mounted WITHOUT the `get_brain_auth_context` dependency; the opaque
# `webhook_uuid` token in the path is the only credential.
webhook_router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCHEDULE = "schedule"
WEBHOOK = "webhook"
SLACK = "slack_trigger"

STATUS_PENDING = "pending_verification"
STATUS_INACTIVE = "inactive"
STATUS_ACTIVE = "active"

EXEC_PENDING = "pending"
EXEC_RUNNING = "running"
EXEC_COMPLETED = "completed"
EXEC_FAILED = "failed"
EXEC_CANCELLED = "cancelled"
EXEC_MISSED = "missed"

DEFAULT_MAX_FAILURE_COUNT = 5
_SCHEDULER_TICK_SECONDS = 20
_CRON_SEARCH_LIMIT_MINUTES = 60 * 24 * 366  # search up to a year ahead


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _store_root() -> Path:
    root = Path.home() / ".undisclosed" / "triggers"
    override = env("UNDISCLOSED_TRIGGERS_ROOT", "").strip()
    if override:
        root = Path(override).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _store_path() -> Path:
    return _store_root() / "store.json"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _utcnow()).isoformat()


class _Store:
    """Tiny JSON-backed store with a process-wide lock."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cache: dict[str, Any] | None = None

    def _empty(self) -> dict[str, Any]:
        return {
            "next_trigger_id": 1,
            "next_execution_id": 1,
            "triggers": [],
            "executions": [],
            # Slack thread linkage: {"<channel_id>|<thread_ts>": {project_id,
            # space_id, space_root, ...}}. Written when a run posts to Slack,
            # read when a reply arrives, so a reply-trigger follows up in the
            # exact conversation that opened the thread. See
            # `record_slack_thread_link` / `resolve_slack_thread_link`.
            "slack_threads": {},
        }

    def load(self) -> dict[str, Any]:
        with self._lock:
            if self._cache is not None:
                return self._cache
            path = _store_path()
            data: dict[str, Any]
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    logger.warning(
                        "Corrupt triggers store; starting fresh",
                        extra={"path": str(path)},
                        exc_info=True,
                    )
                    data = self._empty()
            else:
                data = self._empty()
            for key, default in self._empty().items():
                data.setdefault(key, default)
            self._cache = data
            return data

    def save(self) -> None:
        with self._lock:
            data = self._cache or self._empty()
            path = _store_path()
            text = json.dumps(data, ensure_ascii=False, indent=2)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)

    def update(self, mutate: "Any") -> Any:
        """Run ``mutate(data)`` under the lock and persist the result."""
        with self._lock:
            data = self.load()
            result = mutate(data)
            self.save()
            return result


store = _Store()

# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

_TRIGGER_FIELDS = (
    "name",
    "description",
    "space_id",
    "project_id",
    "scope",
    "trigger_type",
    "status",
    "webhook_url",
    "custom_cron_expression",
    "listener_type",
    "webhook_method",
    "agent_model",
    "task_prompt",
    "custom_task",
    "max_executions_per_hour",
    "max_executions_per_day",
    "is_single_execution",
    "config",
)


def _public_trigger(trigger: dict[str, Any]) -> dict[str, Any]:
    """Return the trigger in the shape `types.Trigger` expects (JSON-safe)."""
    out = dict(trigger)
    # Normalise scope for the client. Legacy rows predate the field: a trigger
    # that carries a project_id is conversation-scoped, otherwise it belongs to
    # the whole workspace. Emitting an explicit value means the UI never has to
    # re-derive it.
    if not out.get("scope"):
        out["scope"] = "conversation" if out.get("project_id") else "workspace"
    return out


def _ensure_webhook_url(trigger: dict[str, Any]) -> bool:
    """Give a webhook/Slack trigger an inbound URL + token if it lacks one.

    Slack triggers created before the backend assigned a URL otherwise stay
    `webhook_url: null` forever and the UI can never show a webhook. Called from
    the list route so an existing automation is repaired on the next read.
    Returns True if the trigger was changed.
    """
    if trigger.get("trigger_type") not in (WEBHOOK, SLACK):
        return False
    if trigger.get("webhook_url"):
        return False
    token = uuid.uuid4().hex
    trigger["webhook_url"] = f"/api/v1/webhook/{token}"
    config = dict(trigger.get("config") or {})
    config.setdefault("webhook_uuid", token)
    trigger["config"] = config
    trigger["updated_at"] = _iso()
    return True


def _find_trigger(data: dict[str, Any], trigger_id: int) -> dict[str, Any] | None:
    for trigger in data["triggers"]:
        if int(trigger.get("id", -1)) == int(trigger_id):
            return trigger
    return None


def _find_execution(
    data: dict[str, Any], execution_id: str
) -> dict[str, Any] | None:
    for execution in data["executions"]:
        if str(execution.get("execution_id")) == str(execution_id):
            return execution
    return None


# ---------------------------------------------------------------------------
# Cron (5-field: minute hour day-of-month month day-of-week)
# ---------------------------------------------------------------------------


def _parse_cron_field(field: str, low: int, high: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        if "/" in part:
            part, _, step_str = part.partition("/")
            try:
                step = max(1, int(step_str))
            except ValueError:
                step = 1
        if part in ("*", ""):
            start, end = low, high
        elif "-" in part:
            a, _, b = part.partition("-")
            try:
                start, end = int(a), int(b)
            except ValueError:
                continue
        else:
            try:
                start = end = int(part)
            except ValueError:
                continue
        if start > end:
            start, end = end, start
        values.update(range(max(low, start), min(high, end) + 1, step))
    return values


def _cron_matches(expression: str, when: datetime) -> bool:
    fields = expression.split()
    if len(fields) != 5:
        return False
    minute, hour, dom, month, dow = fields
    # Python weekday(): Monday=0..Sunday=6; cron dow: Sunday=0..Saturday=6.
    cron_dow = (when.weekday() + 1) % 7
    return (
        when.minute in _parse_cron_field(minute, 0, 59)
        and when.hour in _parse_cron_field(hour, 0, 23)
        and when.day in _parse_cron_field(dom, 1, 31)
        and when.month in _parse_cron_field(month, 1, 12)
        and cron_dow in _parse_cron_field(dow, 0, 6)
    )


def _compute_next_run(expression: str, after: datetime) -> datetime | None:
    """Return the first matching minute strictly after ``after`` (or None)."""
    if not expression or len(expression.split()) != 5:
        return None
    candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(_CRON_SEARCH_LIMIT_MINUTES):
        if _cron_matches(expression, candidate):
            return candidate
        candidate += timedelta(minutes=1)
    return None


def _parse_iso(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


# ---------------------------------------------------------------------------
# WebSocket fan-out (execution events)
# ---------------------------------------------------------------------------

# Each connected editor declares which folder-space it owns when it subscribes
# (see `execution_subscribe`), so an execution event can be routed to the ONE
# window that has the trigger's folder open instead of fanned out to every
# client. Without that, a single trigger fires in every open editor at once.
_ws_clients: dict[WebSocket, dict[str, Any]] = {}
_ws_loop: asyncio.AbstractEventLoop | None = None
_ws_lock = threading.Lock()


def _space_id_for_root(root: str | None) -> str | None:
    """Stable folder-space id for a filesystem root.

    Mirrors the Spaces API scheme (`folder_<sha256(normalized root)>[:16]`) so a
    window's open folder can be matched against a trigger's `space_id` with no
    round trip.
    """
    if not root or not root.strip():
        return None
    normalized = os.path.normpath(os.path.expanduser(root.strip()))
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"folder_{digest}"


def _folder_root_for_space_id(space_id: str | None) -> str | None:
    """Reverse of `_space_id_for_root` via the folder registry (best-effort)."""
    if not space_id:
        return None
    try:
        reg_path = Path.home() / ".undisclosed" / "folder_spaces.json"
        if reg_path.exists():
            reg = json.loads(reg_path.read_text(encoding="utf-8"))
            for root, entry in (reg.get("by_root", {}) or {}).items():
                if (entry or {}).get("id") == space_id:
                    return root
    except Exception:
        logger.debug("folder-space reverse lookup failed", exc_info=True)
    return None


# ---------------------------------------------------------------------------
# Slack thread <-> conversation linkage
#
# A schedule trigger scoped to the workspace creates a NEW conversation each
# run, so there is no stable conversation a reply-trigger could target ahead of
# time. The thread is the stable handle: when a run posts to Slack we remember
# which conversation the post came from, keyed by the Slack thread it opened;
# when a reply arrives on that thread we look the conversation back up and run
# the reply inside it. That is what makes trigger 2 "follow up" on the same
# conversation trigger 1 created, run after run.
# ---------------------------------------------------------------------------


def _slack_thread_key(channel_id: str | None, thread_ts: str | None) -> str | None:
    if not channel_id or not thread_ts:
        return None
    return f"{channel_id}|{thread_ts}"


def _space_for_conversation(
    project_id: str | None,
) -> tuple[str | None, str | None]:
    """Best-effort (space_id, root) for a conversation via folder_spaces.json."""
    if not project_id:
        return None, None
    try:
        reg_path = Path.home() / ".undisclosed" / "folder_spaces.json"
        if not reg_path.exists():
            return None, None
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        for root, entry in (reg.get("by_root", {}) or {}).items():
            conversations = (entry or {}).get("conversations", {}) or {}
            if project_id in conversations:
                return (entry or {}).get("id"), root
    except Exception:
        logger.debug("folder-space lookup for conversation failed", exc_info=True)
    return None, None


def record_slack_thread_link(
    channel_id: str | None,
    thread_ts: str | None,
    project_id: str | None,
    *,
    message_ts: str | None = None,
) -> None:
    """Remember that Slack thread ``thread_ts`` maps to conversation
    ``project_id``. Called from the Slack toolkit right after it posts, so an
    inbound reply on that thread can be routed back into the same conversation.
    No-op when the key or the conversation is missing."""
    key = _slack_thread_key(channel_id, thread_ts)
    if not key or not project_id:
        return
    space_id, root = _space_for_conversation(project_id)

    def mutate(data: dict[str, Any]) -> None:
        threads = data.setdefault("slack_threads", {})
        threads[key] = {
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "message_ts": message_ts,
            "project_id": project_id,
            "space_id": space_id,
            "space_root": root,
            "updated_at": _iso(),
        }

    try:
        store.update(mutate)
        logger.info(
            "linked slack thread %s -> conversation %s", key, project_id
        )
    except Exception:
        logger.warning("failed to record slack thread link", exc_info=True)


def resolve_slack_thread_link(
    channel_id: str | None, thread_ts: str | None
) -> dict[str, Any] | None:
    """Return the conversation link for a Slack thread, or None if unknown."""
    key = _slack_thread_key(channel_id, thread_ts)
    if not key:
        return None
    try:
        link = (store.load().get("slack_threads") or {}).get(key)
    except Exception:
        logger.debug("slack thread link lookup failed", exc_info=True)
        return None
    return dict(link) if isinstance(link, dict) else None


async def _ws_send_all(payload: dict[str, Any], clients: list[WebSocket]) -> None:
    for client in clients:
        try:
            await client.send_json(payload)
        except Exception:
            with _ws_lock:
                _ws_clients.pop(client, None)


def broadcast(payload: dict[str, Any]) -> None:
    """Broadcast an execution event, safe to call from the scheduler thread.

    When the event names a `space_id`, deliver it ONLY to the editor(s) whose
    open folder is that space. Editors that declared no space (or an older
    client that never sends one) are unknown targets: if nothing matches we fall
    back to fanning out to everyone so a trigger still runs rather than silently
    doing nothing.
    """
    loop = _ws_loop
    if loop is None:
        return
    with _ws_lock:
        clients = list(_ws_clients.items())
    if not clients:
        return
    target_space = payload.get("space_id")
    recipients: list[WebSocket]
    if target_space:
        recipients = [
            ws for ws, meta in clients if meta.get("space_id") == target_space
        ] or [ws for ws, _ in clients]
    else:
        recipients = [ws for ws, _ in clients]
    try:
        asyncio.run_coroutine_threadsafe(_ws_send_all(payload, recipients), loop)
    except Exception:
        logger.debug("execution broadcast failed", exc_info=True)


@ws_router.websocket("/execution/subscribe")
async def execution_subscribe(websocket: WebSocket) -> None:
    global _ws_loop
    await websocket.accept()
    _ws_loop = asyncio.get_running_loop()
    session_id = str(uuid.uuid4())
    with _ws_lock:
        _ws_clients[websocket] = {"space_id": None, "session_id": session_id}
    try:
        await websocket.send_json(
            {
                "type": "connected",
                "session_id": session_id,
                "timestamp": _iso(),
            }
        )
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(message, dict):
                continue
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif message.get("type") == "subscribe":
                session_id = str(message.get("session_id") or session_id)
                # The editor tells us which folder it has open (its space) so we
                # can route execution events to it and not to every other window.
                space_root = message.get("space_root")
                space_id = message.get("space_id") or _space_id_for_root(
                    space_root if isinstance(space_root, str) else None
                )
                with _ws_lock:
                    _ws_clients[websocket] = {
                        "space_id": space_id,
                        "session_id": session_id,
                    }
                # Local Brain is single-user (NoneAuth); accept the subscription
                # and confirm so the panel leaves the "disconnected" state.
                await websocket.send_json(
                    {
                        "type": "connected",
                        "session_id": session_id,
                        "timestamp": _iso(),
                    }
                )
            elif message.get("type") == "ack":
                # Acknowledgements are informational only in the local runtime.
                continue
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("execution ws closed", exc_info=True)
    finally:
        with _ws_lock:
            _ws_clients.pop(websocket, None)


# ---------------------------------------------------------------------------
# Execution helpers
# ---------------------------------------------------------------------------


def _create_execution(
    data: dict[str, Any],
    trigger: dict[str, Any],
    *,
    execution_type: str,
    input_data: dict[str, Any] | None = None,
    max_retries: int = 0,
    attempts: int = 1,
) -> dict[str, Any]:
    execution_id = str(uuid.uuid4())
    execution = {
        "id": data["next_execution_id"],
        "execution_id": execution_id,
        "trigger_id": trigger["id"],
        "execution_type": execution_type,
        "status": EXEC_PENDING,
        "started_at": None,
        "completed_at": None,
        "duration_seconds": None,
        "input_data": input_data or {},
        "output_data": {},
        "error_message": None,
        "skip_reason": None,
        "attempts": attempts,
        "max_retries": max_retries,
        "tokens_used": 0,
        "tools_executed": {},
        "created_at": _iso(),
        "updated_at": _iso(),
    }
    data["next_execution_id"] += 1
    data["executions"].append(execution)
    return execution


def _execution_created_event(
    execution: dict[str, Any],
    trigger: dict[str, Any],
    project_id: str | None,
    *,
    space_id_override: str | None = None,
    space_root_override: str | None = None,
) -> dict[str, Any]:
    # A Slack-thread follow-up carries the conversation (and space) it must run
    # in; those override the trigger's own scope for this one execution.
    space_id = space_id_override or trigger.get("space_id")
    space_root = space_root_override or _folder_root_for_space_id(space_id)
    return {
        "type": "execution_created",
        "execution_id": execution["execution_id"],
        "trigger_id": trigger["id"],
        "trigger_type": trigger.get("trigger_type"),
        "status": execution["status"],
        "execution_type": execution["execution_type"],
        "input_data": execution.get("input_data") or {},
        "user_id": trigger.get("user_id", "local"),
        "project_id": project_id or trigger.get("project_id"),
        # The trigger is scoped to a folder-space, not just a project id. The
        # panel rehydrates the target project when it isn't loaded locally, and
        # without this it falls back to whatever space is currently active —
        # silently re-filing an automation's project under the folder the user
        # happens to have open. Forward it so the client can run it in the right
        # place.
        "space_id": space_id,
        # Root path of that space, so a client can confirm ownership by comparing
        # it to its own open folder even when its space store isn't hydrated.
        "space_root": space_root,
        "timestamp": _iso(),
        "task_prompt": trigger.get("task_prompt"),
    }


def dispatch_slack_event(
    event: dict[str, Any], *, channel_id: str | None = None
) -> int:
    """Fire every ACTIVE Slack trigger that matches an inbound Slack event.

    Called by the Socket Mode listener (`app/service/slack_socket_listener.py`)
    for each `events_api` payload Slack pushes down the outbound websocket,
    which is how a locally-hosted Brain receives Slack events without a public
    ingress URL. A trigger bound to a channel (`config.channel_id`) only fires
    for that channel; a trigger with no channel filter fires for any event. Each
    match creates a pending execution and broadcasts `execution_created`, exactly
    like a fired schedule trigger, so the panel's task executor runs it.

    Returns the number of executions fired. Safe to call from the listener's own
    thread/event loop.
    """
    fired: list[dict[str, Any]] = []

    # Thread follow-up: if this inbound event is a reply inside a Slack thread
    # that a previous run opened, run the reply in the conversation that opened
    # the thread, not a fresh one. `thread_ts` is the root of the thread (equal
    # to the parent message's ts); a top-level message has no thread_ts, so fall
    # back to its own ts in case the trigger itself is the thread opener.
    event_channel = channel_id or (
        event.get("channel") if isinstance(event, dict) else None
    )
    thread_key = None
    if isinstance(event, dict):
        thread_key = event.get("thread_ts") or event.get("ts")
    link = resolve_slack_thread_link(event_channel, thread_key)
    linked_project_id = (link or {}).get("project_id")
    linked_space_id = (link or {}).get("space_id")
    linked_space_root = (link or {}).get("space_root")

    def mutate(data: dict[str, Any]) -> None:
        for trigger in data["triggers"]:
            if trigger.get("trigger_type") != SLACK:
                continue
            if trigger.get("status") != STATUS_ACTIVE:
                continue
            config = trigger.get("config") or {}
            want_channel = str(config.get("channel_id") or "").strip()
            if want_channel and want_channel != (channel_id or ""):
                continue
            execution = _create_execution(
                data,
                trigger,
                execution_type="slack",
                input_data=event,
                max_retries=config.get(
                    "max_failure_count", DEFAULT_MAX_FAILURE_COUNT
                ),
            )
            trigger["last_executed_at"] = _iso()
            trigger["last_execution_status"] = EXEC_PENDING
            trigger["execution_count"] = int(trigger.get("execution_count", 0)) + 1
            fired.append(
                _execution_created_event(
                    execution,
                    trigger,
                    linked_project_id or trigger.get("project_id"),
                    space_id_override=linked_space_id,
                    space_root_override=linked_space_root,
                )
            )

    store.update(mutate)
    for payload in fired:
        broadcast(payload)
    if fired:
        logger.info("dispatched %d slack execution(s) from inbound event", len(fired))
    return len(fired)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

_scheduler_started = False
_scheduler_lock = threading.Lock()


def _run_due_schedule_triggers() -> None:
    now = _utcnow()
    fired: list[tuple[dict[str, Any], dict[str, Any], str | None]] = []

    def mutate(data: dict[str, Any]) -> None:
        for trigger in data["triggers"]:
            if trigger.get("trigger_type") != SCHEDULE:
                continue
            if trigger.get("status") != STATUS_ACTIVE:
                continue
            expression = trigger.get("custom_cron_expression") or ""
            due = _parse_iso(trigger.get("next_run_at"))
            if due is None:
                due = _compute_next_run(expression, now)
                trigger["next_run_at"] = _iso(due) if due else None
                continue
            if due > now:
                continue
            # Fire exactly once for this due instant, then advance the cursor.
            execution = _create_execution(
                data,
                trigger,
                execution_type="scheduled",
                input_data={"scheduled_at": _iso(due)},
                max_retries=trigger.get("config", {}).get(
                    "max_failure_count", DEFAULT_MAX_FAILURE_COUNT
                ),
            )
            trigger["last_executed_at"] = _iso(now)
            trigger["last_execution_status"] = EXEC_PENDING
            trigger["execution_count"] = int(trigger.get("execution_count", 0)) + 1
            nxt = _compute_next_run(expression, now)
            trigger["next_run_at"] = _iso(nxt) if nxt else None
            if trigger.get("is_single_execution") and nxt is None:
                trigger["status"] = STATUS_INACTIVE
            fired.append((trigger, execution, trigger.get("project_id")))

    try:
        store.update(mutate)
    except Exception:
        logger.warning("scheduler tick failed", exc_info=True)
        return

    for trigger, execution, project_id in fired:
        broadcast(_execution_created_event(execution, trigger, project_id))


def _ensure_scheduler() -> None:
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True

    def loop() -> None:
        while True:
            try:
                _run_due_schedule_triggers()
            except Exception:
                logger.warning("scheduler loop error", exc_info=True)
            threading.Event().wait(_SCHEDULER_TICK_SECONDS)

    thread = threading.Thread(
        target=loop, name="trigger-scheduler", daemon=True
    )
    thread.start()
    logger.info("Trigger scheduler started (tick=%ss)", _SCHEDULER_TICK_SECONDS)


_ensure_scheduler()


# ---------------------------------------------------------------------------
# Trigger type configuration schemas
# ---------------------------------------------------------------------------


def _config_schema(trigger_type: str) -> dict[str, Any]:
    if trigger_type == WEBHOOK:
        return {
            "type": "object",
            "properties": {
                "authentication_required": {
                    "type": "boolean",
                    "title": "Require signature verification",
                    "default": False,
                },
                "signing_secret": {
                    "type": "string",
                    "title": "Signing secret",
                    "secret": True,
                },
            },
        }
    if trigger_type == SLACK:
        return {
            "type": "object",
            "properties": {
                "bot_token": {
                    "type": "string",
                    "title": "Bot token",
                    "secret": True,
                },
                "signing_secret": {
                    "type": "string",
                    "title": "Signing secret",
                    "secret": True,
                },
                "channel_id": {
                    "type": "string",
                    "title": "Channel ID",
                },
            },
            "required": ["bot_token"],
        }
    # Schedule uses the dedicated SchedulePicker, not a dynamic schema.
    return {"type": "object", "properties": {}}


# ---------------------------------------------------------------------------
# Trigger routes
# ---------------------------------------------------------------------------


@router.get("/trigger/")
async def list_triggers(
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=500),
    trigger_type: str | None = Query(None),
    status: str | None = Query(None),
    project_id: str | None = Query(None),
    space_id: str | None = Query(None),
    scope: str | None = Query(None),
) -> dict[str, Any]:
    data = store.load()
    # Repair webhook/Slack triggers that predate the inbound-URL assignment so
    # their webhook becomes visible without needing a re-activate.
    if any(
        t.get("trigger_type") in (WEBHOOK, SLACK) and not t.get("webhook_url")
        for t in data["triggers"]
    ):
        store.update(
            lambda d: [
                _ensure_webhook_url(t) for t in d["triggers"]
            ]  # persist any repairs
        )
        data = store.load()
    items = list(data["triggers"])
    if trigger_type:
        items = [t for t in items if t.get("trigger_type") == trigger_type]
    if status:
        items = [t for t in items if t.get("status") == status]
    if project_id:
        items = [t for t in items if t.get("project_id") == project_id]
    if space_id:
        # Workspace listing: every trigger filed under this folder-space, both
        # workspace-scoped and conversation-scoped. The client narrows further.
        items = [t for t in items if t.get("space_id") == space_id]
    if scope:
        items = [
            t
            for t in items
            if (t.get("scope") or ("conversation" if t.get("project_id") else "workspace"))
            == scope
        ]
    items.sort(key=lambda t: t.get("created_at") or "", reverse=True)
    total = len(items)
    start = (page - 1) * size
    return {
        "items": [_public_trigger(t) for t in items[start : start + size]],
        "total": total,
        "page": page,
        "size": size,
    }


@router.get("/trigger/{trigger_type}/config")
async def get_trigger_config(trigger_type: str) -> dict[str, Any]:
    if trigger_type not in (SCHEDULE, WEBHOOK, SLACK):
        raise HTTPException(status_code=404, detail="Unknown trigger type")
    return {"trigger_type": trigger_type, "schema_": _config_schema(trigger_type)}


@router.get("/trigger/{trigger_id}")
async def get_trigger(trigger_id: int) -> dict[str, Any]:
    trigger = _find_trigger(store.load(), trigger_id)
    if trigger is None:
        raise HTTPException(status_code=404, detail="Trigger not found")
    return _public_trigger(trigger)


@router.post("/trigger/", status_code=201)
async def create_trigger(
    payload: dict[str, Any] = Body(default_factory=dict),
    auth: BrainAuthContext = Depends(get_brain_auth_context),
) -> dict[str, Any]:
    trigger_type = payload.get("trigger_type") or SCHEDULE
    if trigger_type not in (SCHEDULE, WEBHOOK, SLACK):
        raise HTTPException(status_code=400, detail="Invalid trigger_type")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    def mutate(data: dict[str, Any]) -> dict[str, Any]:
        trigger_id = data["next_trigger_id"]
        data["next_trigger_id"] += 1
        trigger: dict[str, Any] = {
            "id": trigger_id,
            "user_id": auth.user_id,
            "name": name,
            "description": payload.get("description") or "",
            "space_id": payload.get("space_id"),
            "project_id": payload.get("project_id"),
            # "workspace" = attached to the folder-space and visible across every
            # conversation in it; "conversation" = attached to one project.
            "scope": payload.get("scope")
            or ("conversation" if payload.get("project_id") else "workspace"),
            "trigger_type": trigger_type,
            "status": STATUS_PENDING
            if trigger_type in (WEBHOOK, SLACK)
            else STATUS_INACTIVE,
            "webhook_url": payload.get("webhook_url"),
            "custom_cron_expression": payload.get("custom_cron_expression")
            or ("0 0 * * *" if trigger_type == SCHEDULE else None),
            "listener_type": payload.get("listener_type"),
            "webhook_method": payload.get("webhook_method") or "POST",
            "agent_model": payload.get("agent_model") or "",
            "task_prompt": payload.get("task_prompt") or "",
            "custom_task": payload.get("custom_task") or {},
            "max_executions_per_hour": payload.get("max_executions_per_hour"),
            "max_executions_per_day": payload.get("max_executions_per_day"),
            "is_single_execution": bool(payload.get("is_single_execution", False)),
            "config": payload.get("config") or {},
            "last_executed_at": None,
            "last_execution_status": None,
            "next_run_at": None,
            "consecutive_failures": 0,
            "auto_disabled_at": None,
            "execution_count": 0,
            "created_at": _iso(),
            "updated_at": _iso(),
        }
        if trigger_type in (WEBHOOK, SLACK):
            # Both webhook and Slack (Events API) triggers are driven by an
            # inbound URL, so both get a webhook_url + opaque token. Without
            # this a Slack automation had `webhook_url: null` and the UI could
            # never show or hand out a webhook.
            token = uuid.uuid4().hex
            config = dict(trigger["config"])
            config.setdefault("webhook_uuid", token)
            trigger["config"] = config
            trigger["webhook_url"] = (
                payload.get("webhook_url") or f"/api/v1/webhook/{token}"
            )
        data["triggers"].append(trigger)
        return trigger

    trigger = store.update(mutate)
    return _public_trigger(trigger)


@router.put("/trigger/{trigger_id}")
async def update_trigger(
    trigger_id: int, payload: dict[str, Any] = Body(default_factory=dict)
) -> dict[str, Any]:
    def mutate(data: dict[str, Any]) -> dict[str, Any]:
        trigger = _find_trigger(data, trigger_id)
        if trigger is None:
            raise HTTPException(status_code=404, detail="Trigger not found")
        for field in _TRIGGER_FIELDS:
            if field in payload:
                trigger[field] = payload[field]
        trigger["updated_at"] = _iso()
        if trigger.get("status") == STATUS_ACTIVE:
            nxt = _compute_next_run(
                trigger.get("custom_cron_expression") or "", _utcnow()
            )
            trigger["next_run_at"] = _iso(nxt) if nxt else None
        return trigger

    return _public_trigger(store.update(mutate))


@router.delete("/trigger/{trigger_id}", status_code=204)
async def delete_trigger(trigger_id: int) -> Response:
    def mutate(data: dict[str, Any]) -> None:
        trigger = _find_trigger(data, trigger_id)
        if trigger is None:
            raise HTTPException(status_code=404, detail="Trigger not found")
        data["triggers"].remove(trigger)
        data["executions"] = [
            e for e in data["executions"] if int(e.get("trigger_id", -1)) != trigger_id
        ]

    store.update(mutate)
    return Response(status_code=204)


@router.post("/trigger/{trigger_id}/activate")
async def activate_trigger(trigger_id: int) -> dict[str, Any]:
    def mutate(data: dict[str, Any]) -> dict[str, Any]:
        trigger = _find_trigger(data, trigger_id)
        if trigger is None:
            raise HTTPException(status_code=404, detail="Trigger not found")
        trigger["status"] = STATUS_ACTIVE
        trigger["auto_disabled_at"] = None
        trigger["consecutive_failures"] = 0
        trigger["updated_at"] = _iso()
        if trigger.get("trigger_type") == SCHEDULE:
            nxt = _compute_next_run(
                trigger.get("custom_cron_expression") or "", _utcnow()
            )
            trigger["next_run_at"] = _iso(nxt) if nxt else None
        elif trigger.get("trigger_type") in (WEBHOOK, SLACK):
            _ensure_webhook_url(trigger)
        return trigger

    return _public_trigger(store.update(mutate))


@router.post("/trigger/{trigger_id}/deactivate")
async def deactivate_trigger(trigger_id: int) -> dict[str, Any]:
    def mutate(data: dict[str, Any]) -> dict[str, Any]:
        trigger = _find_trigger(data, trigger_id)
        if trigger is None:
            raise HTTPException(status_code=404, detail="Trigger not found")
        trigger["status"] = STATUS_INACTIVE
        trigger["next_run_at"] = None
        trigger["updated_at"] = _iso()
        return trigger

    return _public_trigger(store.update(mutate))


# ---------------------------------------------------------------------------
# Inbound webhook receiver (public — token is the credential)
# ---------------------------------------------------------------------------


@webhook_router.post("/webhook/{token}")
async def receive_webhook(token: str, request: Request) -> dict[str, Any]:
    """Accept an inbound call for the trigger whose token matches.

    This is what the `webhook_url` handed to the user actually points at;
    without it the URL was dead (`404`). A Slack Events API URL-verification
    handshake is echoed back so the URL can be saved in Slack. Any other
    payload becomes a pending execution, broadcast over `/execution/subscribe`
    exactly like a fired schedule trigger.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {"payload": payload}

    # Slack (and any well-behaved source) URL verification handshake.
    if payload.get("type") == "url_verification" and payload.get("challenge"):
        return {"challenge": payload["challenge"]}

    fired: dict[str, Any] | None = None

    def mutate(data: dict[str, Any]) -> None:
        nonlocal fired
        for trigger in data["triggers"]:
            config = trigger.get("config") or {}
            token_match = config.get("webhook_uuid") == token or str(
                trigger.get("webhook_url") or ""
            ).endswith(f"/{token}")
            if not token_match:
                continue
            if trigger.get("status") != STATUS_ACTIVE:
                raise HTTPException(
                    status_code=409,
                    detail="Trigger is not active; enable it before sending webhooks",
                )
            execution = _create_execution(
                data,
                trigger,
                execution_type="webhook",
                input_data=payload,
                max_retries=config.get(
                    "max_failure_count", DEFAULT_MAX_FAILURE_COUNT
                ),
            )
            trigger["last_executed_at"] = _iso()
            trigger["last_execution_status"] = EXEC_PENDING
            trigger["execution_count"] = int(trigger.get("execution_count", 0)) + 1
            event = _execution_created_event(
                execution, trigger, trigger.get("project_id")
            )
            event["_execution_id"] = execution["execution_id"]
            fired = event
            return

    store.update(mutate)
    if fired is None:
        raise HTTPException(status_code=404, detail="Unknown webhook token")
    execution_id = fired.pop("_execution_id")
    broadcast(fired)
    return {"status": "accepted", "execution_id": execution_id}


@router.get("/trigger/{trigger_id}/executions")
async def list_trigger_executions(
    trigger_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=500),
) -> dict[str, Any]:
    data = store.load()
    if _find_trigger(data, trigger_id) is None:
        raise HTTPException(status_code=404, detail="Trigger not found")
    items = [
        e for e in data["executions"] if int(e.get("trigger_id", -1)) == trigger_id
    ]
    items.sort(key=lambda e: e.get("created_at") or "", reverse=True)
    total = len(items)
    start = (page - 1) * size
    return {
        "items": items[start : start + size],
        "total": total,
        "page": page,
        "size": size,
    }


# ---------------------------------------------------------------------------
# Execution routes
# ---------------------------------------------------------------------------


@router.put("/execution/{execution_id}")
async def update_execution(
    execution_id: str, payload: dict[str, Any] = Body(default_factory=dict)
) -> dict[str, Any]:
    broadcast_payload: dict[str, Any] | None = None

    def mutate(data: dict[str, Any]) -> dict[str, Any]:
        nonlocal broadcast_payload
        execution = _find_execution(data, execution_id)
        if execution is None:
            raise HTTPException(status_code=404, detail="Execution not found")
        allowed = (
            "status",
            "started_at",
            "completed_at",
            "duration_seconds",
            "output_data",
            "error_message",
            "skip_reason",
            "attempts",
            "tokens_used",
            "tools_executed",
        )
        updated_fields = [f for f in allowed if f in payload]
        for field in updated_fields:
            execution[field] = payload[field]
        execution["updated_at"] = _iso()
        trigger = _find_trigger(data, int(execution.get("trigger_id", -1)))
        if trigger is not None and "status" in updated_fields:
            trigger["last_execution_status"] = execution["status"]
            if execution["status"] == EXEC_FAILED:
                trigger["consecutive_failures"] = (
                    int(trigger.get("consecutive_failures", 0)) + 1
                )
            elif execution["status"] == EXEC_COMPLETED:
                trigger["consecutive_failures"] = 0
            trigger["updated_at"] = _iso()
        broadcast_payload = {
            "type": "execution_updated",
            "execution_id": execution["execution_id"],
            "trigger_id": execution.get("trigger_id"),
            "status": execution.get("status"),
            "updated_fields": updated_fields,
            "user_id": (trigger or {}).get("user_id", "local"),
            "project_id": (trigger or {}).get("project_id"),
            # Carry the trigger's space so the event routes to the owning editor
            # (and its completion toast doesn't leak into every window).
            "space_id": (trigger or {}).get("space_id"),
            "space_root": _folder_root_for_space_id((trigger or {}).get("space_id")),
            "timestamp": _iso(),
            "task_prompt": (trigger or {}).get("task_prompt"),
        }
        return execution

    execution = store.update(mutate)
    if broadcast_payload is not None:
        broadcast(broadcast_payload)
    return execution


@router.post("/execution/{execution_id}/retry", status_code=201)
async def retry_execution(execution_id: str) -> dict[str, Any]:
    created: dict[str, Any] | None = None
    event: dict[str, Any] | None = None

    def mutate(data: dict[str, Any]) -> None:
        nonlocal created, event
        source = _find_execution(data, execution_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Execution not found")
        trigger = _find_trigger(data, int(source.get("trigger_id", -1)))
        if trigger is None:
            raise HTTPException(status_code=404, detail="Trigger not found")
        created = _create_execution(
            data,
            trigger,
            execution_type=source.get("execution_type") or "scheduled",
            input_data=source.get("input_data") or {},
            max_retries=int(source.get("max_retries", 0)),
            attempts=int(source.get("attempts", 1)) + 1,
        )
        event = _execution_created_event(created, trigger, trigger.get("project_id"))

    store.update(mutate)
    if event is not None:
        broadcast(event)
    return created or {}


__all__ = ["router", "ws_router"]
