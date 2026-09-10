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

"""Live browser bridge for the editor-first (Theia) agent panel.

The desktop app shows the agent's browser by sliding a native Electron
`WebContentsView` over the chat pane and letting the user drive it with native
input ("take control"). A browser-based editor (Theia) has no native webview, so
this bridge reproduces the SAME capability over CDP instead.

The agent drives its Chromium through a Node/TypeScript Playwright (the Python
`playwright` package is NOT installed), so this talks **raw CDP over a
WebSocket** — no extra dependency, just `httpx` (target discovery) and
`websockets` (the DevTools socket), both already present:

  * find the page target the agent is on (`/json`),
  * connect to its DevTools WebSocket (a second client alongside the agent — the
    protocol allows it),
  * `Emulation.setDeviceMetricsOverride` (the agent's window is offscreen, so
    without a forced render surface Chromium never composites → no frames),
  * `Page.startScreencast` → relay JPEG frames to the panel,
  * forward the user's mouse/keyboard back as `Input.dispatch*` so they can
    click, type, scroll and log in.

Everything stays on localhost. Auth is intentionally light: the Brain binds to
localhost and the browser WebSocket API can't send an Authorization header.
"""

import asyncio
import json
import logging
from typing import Any

import httpx
import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.component.environment import env

logger = logging.getLogger("browser_stream")

router = APIRouter()

# Common non-printable keys → Windows virtual-key codes so CDP raises the right
# key events. Printable characters are sent as `keyDown` with `text`.
_VK: dict[str, int] = {
    "Enter": 13,
    "Backspace": 8,
    "Tab": 9,
    "Escape": 27,
    "ArrowLeft": 37,
    "ArrowUp": 38,
    "ArrowRight": 39,
    "ArrowDown": 40,
    "Delete": 46,
    "Home": 36,
    "End": 35,
    "PageUp": 33,
    "PageDown": 34,
    " ": 32,
    "Shift": 16,
    "Control": 17,
    "Alt": 18,
    "Meta": 91,
}
_BUTTONS = ("left", "middle", "right")


def _browser_port(port_override: str | None) -> int:
    if port_override:
        try:
            return int(port_override)
        except (TypeError, ValueError):
            pass
    try:
        return int(env("browser_port", "9222"))
    except (TypeError, ValueError):
        return 9222


async def _discover_page(port: int) -> tuple[str, str] | None:
    """Return (devtools_ws_url, page_url) for the page the agent is on.

    Prefer the last non-blank page target (the agent navigates the most-recent
    tab); fall back to the last page target.
    """
    url = f"http://localhost:{port}/json"
    # Short timeout: this is localhost, and we poll it repeatedly while waiting
    # for the agent to open a page (see browser_stream) — a long timeout would
    # make each poll drag and each non-listening candidate port stall the scan.
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=1.5)
        targets = resp.json()
    pages = [
        t
        for t in targets
        if t.get("type") == "page"
        and not str(t.get("url", "")).startswith("devtools://")
        and t.get("webSocketDebuggerUrl")
    ]
    if not pages:
        return None
    chosen = pages[-1]
    for t in pages:
        u = str(t.get("url", ""))
        if u and not u.startswith("about:blank"):
            chosen = t
    return chosen["webSocketDebuggerUrl"], str(chosen.get("url", ""))


async def _discover_page_any_port(preferred: int) -> tuple[str, str, int] | None:
    """Find a live agent page across likely CDP ports, returning
    (devtools_ws_url, page_url, port).

    The bridge historically assumed `browser_port` (default 9222), but the agent
    can end up on a nearby port (e.g. 9224 when 9222 is taken), which left the
    live view permanently "offline" against the wrong Chromium. Try the caller's
    port first, then scan the small range the launcher uses. Non-listening ports
    fail fast (connection refused), so this stays cheap.
    """
    candidates: list[int] = [preferred]
    for p in range(9222, 9227):
        if p not in candidates:
            candidates.append(p)
    for p in candidates:
        try:
            found = await _discover_page(p)
        except Exception:
            found = None
        if found is not None:
            return found[0], found[1], p
    return None


async def _list_pages(port: int) -> list[dict[str, Any]]:
    """All live (non-devtools, ws-capable) page targets on `port`, in the order
    Chrome's /json returns them (newest first). Used by the tab-follow watcher."""
    url = f"http://localhost:{port}/json"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=1.5)
        targets = resp.json()
    return [
        t
        for t in targets
        if t.get("type") == "page"
        and not str(t.get("url", "")).startswith("devtools://")
        and t.get("webSocketDebuggerUrl")
    ]


class _Cdp:
    """Minimal CDP client over one DevTools WebSocket (fire-and-forget sends)."""

    def __init__(self, ws: Any):
        self._ws = ws
        self._id = 0

    async def send(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._id += 1
        await self._ws.send(
            json.dumps({"id": self._id, "method": method, "params": params or {}})
        )


async def _configure_screencast(
    cdp: _Cdp,
    css_width: int,
    css_height: int,
    device_scale: float,
    quality: int,
    *,
    stop_first: bool,
) -> None:
    """Point the screencast at a CSS viewport rendered at `device_scale` DPR.

    Quality comes from BOTH knobs: `device_scale` (capture at the display's real
    pixel ratio so a Retina panel isn't upscaling a 1x frame) and the JPEG
    `quality`. `maxWidth/Height` are DEVICE pixels, so we pass css × dpr to avoid
    Chromium downscaling the crisp capture back down.
    """
    if stop_first:
        await cdp.send("Page.stopScreencast")
    await cdp.send(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": css_width,
            "height": css_height,
            "deviceScaleFactor": device_scale,
            "mobile": False,
        },
    )
    await cdp.send(
        "Page.startScreencast",
        {
            "format": "jpeg",
            "quality": quality,
            "maxWidth": int(css_width * device_scale),
            "maxHeight": int(css_height * device_scale),
            "everyNthFrame": 1,
        },
    )


def _modifier_bits(mods: dict[str, Any] | None) -> int:
    """CDP modifier bitmask: Alt=1, Ctrl=2, Meta=4, Shift=8."""
    if not mods:
        return 0
    bits = 0
    if mods.get("alt"):
        bits |= 1
    if mods.get("ctrl"):
        bits |= 2
    if mods.get("meta"):
        bits |= 4
    if mods.get("shift"):
        bits |= 8
    return bits


async def _dispatch_input(cdp: _Cdp, msg: dict[str, Any]) -> None:
    """Translate one client input message into a CDP Input.* command."""
    kind = msg.get("type")
    mods = _modifier_bits(msg.get("modifiers"))

    if kind in ("mousemove", "mousedown", "mouseup"):
        cdp_type = {
            "mousemove": "mouseMoved",
            "mousedown": "mousePressed",
            "mouseup": "mouseReleased",
        }[kind]
        button = msg.get("button", "left")
        params: dict[str, Any] = {
            "type": cdp_type,
            "x": float(msg.get("x", 0)),
            "y": float(msg.get("y", 0)),
            "modifiers": mods,
            "button": button if button in _BUTTONS else "none",
            "buttons": int(msg.get("buttons", 0)),
        }
        if cdp_type != "mouseMoved":
            params["clickCount"] = int(msg.get("clickCount", 1))
        await cdp.send("Input.dispatchMouseEvent", params)

    elif kind == "wheel":
        await cdp.send(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseWheel",
                "x": float(msg.get("x", 0)),
                "y": float(msg.get("y", 0)),
                "deltaX": float(msg.get("deltaX", 0)),
                "deltaY": float(msg.get("deltaY", 0)),
                "modifiers": mods,
            },
        )

    elif kind in ("keydown", "keyup"):
        key = msg.get("key", "")
        cdp_type = "keyDown" if kind == "keydown" else "keyUp"
        params = {
            "type": cdp_type,
            "modifiers": mods,
            "key": key,
            "code": msg.get("code", ""),
        }
        vk = _VK.get(key)
        if vk is not None:
            params["windowsVirtualKeyCode"] = vk
            params["nativeVirtualKeyCode"] = vk
        if cdp_type == "keyDown" and len(key) == 1 and vk is None:
            params["text"] = key
        await cdp.send("Input.dispatchKeyEvent", params)


async def _pump_frames(
    cdp_ws: Any, cdp: _Cdp, client: WebSocket
) -> None:
    """Read CDP events; forward screencast frames to the panel (+ack)."""
    async for raw in cdp_ws:
        try:
            evt = json.loads(raw)
        except Exception:
            continue
        if evt.get("method") != "Page.screencastFrame":
            continue
        params = evt.get("params", {})
        await client.send_json(
            {
                "type": "frame",
                "data": params.get("data"),
                "metadata": params.get("metadata"),
            }
        )
        # Chromium stops the screencast unless every frame is acked.
        await cdp.send(
            "Page.screencastFrameAck", {"sessionId": params.get("sessionId")}
        )


@router.websocket("/browser/stream")
async def browser_stream(websocket: WebSocket) -> None:
    """Stream the agent's browser and forward input, over one WebSocket.

    Client → server: `{type: mousemove|mousedown|mouseup|wheel|keydown|keyup,
    ...}` and `{type: "viewport", width, height}`. Server → client:
    `{type:"ready", url}`, `{type:"frame", data:<base64 jpeg>, metadata}`,
    `{type:"error", message}`.
    """
    await websocket.accept()

    quality = int(websocket.query_params.get("quality", "80") or 80)
    width = int(websocket.query_params.get("max_width", "1280") or 1280)
    height = int(websocket.query_params.get("max_height", "800") or 800)
    device_scale = float(websocket.query_params.get("device_scale", "1") or 1)
    port = _browser_port(websocket.query_params.get("port"))

    # Current viewport (mutable: the client's `viewport` messages update it and
    # every rebind re-applies it to the new target).
    cur_w, cur_h, cur_dsf = width, height, device_scale
    # The target we're actively streaming; `desired` is where the watcher wants
    # us next. Swapping between them is a "rebind".
    state: dict[str, Any] = {"ws": None, "cdp": None, "target_id": None}
    desired: dict[str, Any] = {"url": None, "id": None, "page_url": ""}
    rebind = asyncio.Event()
    seen_ids: set[str] = set()
    input_task: asyncio.Task[Any] | None = None
    watch_task: asyncio.Task[Any] | None = None

    async def _connect(devtools: str) -> tuple[Any, _Cdp]:
        ws = await websockets.connect(devtools, max_size=None)
        c = _Cdp(ws)
        await c.send("Page.enable")
        # The agent's window is offscreen; without a forced render surface
        # Chromium never composites the tab, so no frames arrive.
        await _configure_screencast(
            c, cur_w, cur_h, cur_dsf, quality, stop_first=False
        )
        return ws, c

    async def _teardown(ws: Any) -> None:
        if ws is None:
            return
        try:
            # Restore the page: stop the screencast + drop the metrics override.
            await ws.send(
                json.dumps({"id": 99998, "method": "Page.stopScreencast", "params": {}})
            )
            await ws.send(
                json.dumps(
                    {
                        "id": 99999,
                        "method": "Emulation.clearDeviceMetricsOverride",
                        "params": {},
                    }
                )
            )
        except Exception:
            pass
        try:
            await ws.close()
        except Exception:
            pass

    async def _pump_input() -> None:
        nonlocal cur_w, cur_h, cur_dsf
        while True:
            msg = await websocket.receive_json()
            cdp = state["cdp"]
            if msg.get("type") == "viewport":
                try:
                    cur_w = int(msg.get("width", cur_w))
                    cur_h = int(msg.get("height", cur_h))
                    # Clamp DPR so a hostile/huge value can't blow up capture.
                    cur_dsf = max(
                        1.0, min(float(msg.get("deviceScaleFactor", cur_dsf) or 1), 3.0)
                    )
                    if cdp is not None:
                        await _configure_screencast(
                            cdp, cur_w, cur_h, cur_dsf, quality, stop_first=True
                        )
                except Exception:
                    logger.debug("screencast resize failed", exc_info=True)
            elif cdp is not None:
                try:
                    await _dispatch_input(cdp, msg)
                except Exception:
                    logger.debug("input dispatch failed", exc_info=True)

    async def _watch_targets() -> None:
        """Follow the agent across tabs. When it opens a NEW page target, switch
        the live view to it; if the tab we're showing closes, fall back to the
        most recent remaining page. Without this the bridge stayed pinned to the
        target chosen at connect time, so a newly opened tab was never shown."""
        while True:
            await asyncio.sleep(1.0)
            try:
                pages = await _list_pages(port)
            except Exception:
                continue
            if not pages:
                continue
            ids = [str(p.get("id")) for p in pages if p.get("id")]
            id_set = set(ids)
            new_ids = [i for i in ids if i not in seen_ids]
            target: dict[str, Any] | None = None
            if new_ids:
                # Prefer a non-blank newly-opened tab (the agent navigates it a
                # beat after opening); else take the newest new target.
                for p in pages:
                    if str(p.get("id")) in new_ids and not str(
                        p.get("url", "")
                    ).startswith("about:blank"):
                        target = p
                        break
                if target is None:
                    target = next(
                        (p for p in pages if str(p.get("id")) == new_ids[0]), None
                    )
            elif state["target_id"] not in id_set:
                # The tab we were streaming closed — fall back to a live page.
                target = pages[0]
                for p in pages:
                    if not str(p.get("url", "")).startswith("about:blank"):
                        target = p
                        break
            seen_ids.update(ids)
            if target is not None:
                tws = target.get("webSocketDebuggerUrl")
                tid = str(target.get("id"))
                if tws and tid != state["target_id"]:
                    desired["url"] = tws
                    desired["id"] = tid
                    desired["page_url"] = str(target.get("url", ""))
                    rebind.set()

    try:
        # Poll for a page instead of failing on the first miss. The agent often
        # launches the browser a beat before it opens a page (or its CDP is on a
        # nearby port), which used to yield an immediate, permanent "offline".
        # The client stays in its initial "Connecting…" state until we send
        # "ready" or "error", so this just waits for the page to appear.
        loop = asyncio.get_event_loop()
        deadline = loop.time() + 12.0
        discovered = None
        while loop.time() < deadline:
            discovered = await _discover_page_any_port(port)
            if discovered is not None:
                break
            await asyncio.sleep(0.4)
        if discovered is None:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "The agent has no browser page open yet. Ask it "
                    "to visit a page — this view picks it up automatically once "
                    "it does.",
                }
            )
            return
        devtools_url, page_url, port = discovered
        desired["url"] = devtools_url
        desired["page_url"] = page_url
        # Seed the "seen" set + our target id from the current target list so the
        # watcher only reacts to tabs opened AFTER we connect.
        try:
            for p in await _list_pages(port):
                if p.get("id"):
                    seen_ids.add(str(p.get("id")))
                if p.get("webSocketDebuggerUrl") == devtools_url:
                    desired["id"] = str(p.get("id"))
        except Exception:
            pass

        input_task = asyncio.create_task(_pump_input())
        watch_task = asyncio.create_task(_watch_targets())

        while True:
            ws, cdp = await _connect(desired["url"])
            state["ws"], state["cdp"], state["target_id"] = ws, cdp, desired["id"]
            await websocket.send_json(
                {"type": "ready", "url": desired.get("page_url") or page_url}
            )
            frames_task = asyncio.create_task(_pump_frames(ws, cdp, websocket))
            rebind_wait = asyncio.create_task(rebind.wait())
            done, _pending = await asyncio.wait(
                {frames_task, rebind_wait, input_task, watch_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Client gone or a driver task died → finish.
            if input_task in done or watch_task in done:
                for t in (input_task, watch_task):
                    if t in done:
                        try:
                            t.result()  # retrieve to avoid "exception never retrieved"
                        except Exception:
                            pass
                frames_task.cancel()
                rebind_wait.cancel()
                await _teardown(ws)
                break

            # The watcher wants a different tab → swap the screencast to it.
            if rebind_wait in done:
                rebind.clear()
                frames_task.cancel()
                state["cdp"] = None
                await _teardown(ws)
                continue

            # frames_task ended = the streamed socket closed (tab likely closed).
            # Give the watcher a moment to pick a fallback tab before giving up.
            rebind_wait.cancel()
            await _teardown(ws)
            state["cdp"] = None
            try:
                await asyncio.wait_for(rebind.wait(), timeout=3.0)
                rebind.clear()
                continue
            except asyncio.TimeoutError:
                break

    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - report, never crash the socket
        logger.warning("browser stream failed: %s", exc, exc_info=True)
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        if input_task is not None:
            input_task.cancel()
        if watch_task is not None:
            watch_task.cancel()
        await _teardown(state["ws"])
