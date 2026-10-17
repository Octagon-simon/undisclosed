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
"""Slack Socket Mode listener - inbound Slack events with no public URL.

Why this exists
---------------
The local Brain binds to ``127.0.0.1`` (``main.py``). That means the inbound
webhook URL we hand out for a Slack automation
(``http://localhost:5001/api/v1/webhook/<token>``) is unreachable from Slack's
cloud: Slack cannot route a request to your laptop's loopback interface. So an
Events API webhook can never drive a local automation.

Socket Mode flips the direction. The Brain opens an *outbound* WebSocket to
Slack (``apps.connections.open`` authenticated with the app-level token
``xapp-``), and Slack pushes Events API payloads down that socket. No ingress,
no tunnel, no public URL - which is exactly what a desktop app needs.

Wiring
------
``SLACK_APP_TOKEN`` + ``SLACK_BOT_TOKEN`` are set through the Connectors UI,
persisted to ``~/.undisclosed/.env`` (see
``chat_platform_controller.set_config_env``), which ``env()`` re-reads live from
disk. This service polls those two keys; when both appear it connects, and when
either is cleared it disconnects. No Brain restart, no app restart - enabling
Slack in Connectors is enough.

Each ``events_api`` payload is acknowledged immediately (Slack redelivers an
unacked envelope, which would double-fire) and then routed through
``trigger_controller.dispatch_slack_event``, which creates a pending execution
for every matching active ``slack_trigger`` and broadcasts ``execution_created``
on the same WebSocket the panel already listens on. From there it runs through
the normal trigger execution path.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from typing import TYPE_CHECKING, Any

from app.component.environment import env

if TYPE_CHECKING:  # pragma: no cover - typing only
    from slack_sdk.socket_mode.aiohttp import SocketModeClient

logger = logging.getLogger("slack_socket_listener")

# How often the supervisor re-reads ~/.undisclosed/.env for token changes.
_POLL_SECONDS = 10.0


def _tokens() -> tuple[tuple[str, str] | None, str, str]:
    """Return ((app, bot), app, bot); the first element is None unless both set."""
    app_token = (env("SLACK_APP_TOKEN") or "").strip()
    bot_token = (env("SLACK_BOT_TOKEN") or "").strip()
    if not app_token or not bot_token:
        return None, app_token, bot_token
    return (app_token, bot_token), app_token, bot_token


def _build_client(app_token: str, bot_token: str) -> "SocketModeClient":
    # Imported lazily so the module (and thus Brain startup) does not hard-depend
    # on slack_sdk being importable when Slack is not configured.
    from slack_sdk.socket_mode.aiohttp import SocketModeClient
    from slack_sdk.web.async_client import AsyncWebClient

    client = SocketModeClient(
        app_token=app_token,
        web_client=AsyncWebClient(token=bot_token),
    )
    client.socket_mode_request_listeners.append(_on_request)
    return client


async def _on_request(client: "SocketModeClient", req: Any) -> None:
    """Handle one Socket Mode envelope (runs inside the socket's event loop)."""
    try:
        req_type = getattr(req, "type", None)
        if req_type != "events_api":
            # hello / disconnect / interactive are not inbound automations.
            return

        # Ack first: Slack redelivers an unacknowledged envelope, and the SDK's
        # aiohttp client does not auto-ack, so a slow dispatch would cause the
        # event to be delivered (and fired) more than once.
        with contextlib.suppress(Exception):
            from slack_sdk.socket_mode.response import SocketModeResponse

            await client.send_socket_mode_response(
                SocketModeResponse(envelope_id=req.envelope_id)
            )

        payload = req.payload or {}
        event = payload.get("event") or {}
        if not isinstance(event, dict):
            return

        # Never react to the bot's own posts - that would loop an automation that
        # replies in Slack back into itself.
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            return

        channel_id = event.get("channel")

        # Imported here (not at module import) to avoid an import cycle:
        # trigger_controller imports nothing from this module, but keeping the
        # dependency local makes startup order irrelevant.
        from app.controller import trigger_controller

        fired = trigger_controller.dispatch_slack_event(
            event, channel_id=channel_id
        )
        logger.info(
            "slack event type=%s channel=%s fired=%d",
            event.get("type"),
            channel_id,
            fired,
        )
    except Exception:
        logger.warning("failed to handle slack event", exc_info=True)


async def _serve(stop: threading.Event) -> None:
    """Supervise a single Socket Mode connection until ``stop`` is set."""
    active_signature: tuple[str, str] | None = None
    client: "SocketModeClient | None" = None
    connect_task: asyncio.Future | None = None

    async def _teardown() -> None:
        nonlocal client, connect_task
        if connect_task is not None and not connect_task.done():
            connect_task.cancel()
            with contextlib.suppress(BaseException):
                await connect_task
        connect_task = None
        if client is not None:
            with contextlib.suppress(Exception):
                await client.close()
            client = None

    try:
        while not stop.is_set():
            signature, app_token, bot_token = _tokens()

            if connect_task is not None and connect_task.done():
                exc = connect_task.exception()
                if exc is not None:
                    logger.warning("slack socket mode connect failed: %r", exc)
                    await _teardown()
                    active_signature = None

            if signature != active_signature:
                await _teardown()
                active_signature = signature
                if signature is not None:
                    try:
                        client = _build_client(app_token, bot_token)
                    except Exception:
                        logger.warning(
                            "could not build slack socket mode client",
                            exc_info=True,
                        )
                        client = None
                        active_signature = None
                    else:
                        # Log after connect() resolves so a healthy session is
                        # distinguishable from a silent no-op in the brain log.
                        async def _connect(
                            _client: "SocketModeClient" = client,
                            _app: str = app_token,
                            _bot: str = bot_token,
                        ) -> None:
                            await _client.connect()
                            logger.info(
                                "slack socket mode connected (app=%s..., bot=%s...)",
                                _app[:6],
                                _bot[:6],
                            )

                        connect_task = asyncio.ensure_future(_connect())
                        logger.info(
                            "slack socket mode connecting (app=%s..., bot=%s...)",
                            app_token[:6],
                            bot_token[:6],
                        )

            await asyncio.sleep(_POLL_SECONDS)
    finally:
        await _teardown()


def _worker(stop: threading.Event) -> None:
    try:
        asyncio.run(_serve(stop))
    except Exception:
        logger.warning("slack socket mode worker exited", exc_info=True)


class _SocketModeSupervisor:
    _instance: "_SocketModeSupervisor | None" = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @classmethod
    def instance(cls) -> "_SocketModeSupervisor":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop = threading.Event()
            self._thread = threading.Thread(
                target=_worker,
                args=(self._stop,),
                name="slack-socket-mode",
                daemon=True,
            )
            self._thread.start()
        logger.info("slack socket mode supervisor started")

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            self._thread = None
        self._stop.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        logger.info("slack socket mode supervisor stopped")


def start_slack_socket_listener() -> None:
    """Start the supervisor. Idempotent; a no-op thread if Slack unconfigured.

    Call from Brain startup. The worker holds no Slack connection until
    ``SLACK_APP_TOKEN`` and ``SLACK_BOT_TOKEN`` are present in the live env.
    """
    _SocketModeSupervisor.instance().start()


def stop_slack_socket_listener() -> None:
    """Stop the supervisor and close any active connection (Brain shutdown)."""
    _SocketModeSupervisor.instance().stop()


__all__ = [
    "start_slack_socket_listener",
    "stop_slack_socket_listener",
]
