# Copyright (c) 2026 Simon Ugorji
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Desktop control: read a real app's UI tree, then act on it.

The app camera looks at a window; this acts on it. Together they are the
see/act loop for anything that is not a web page: Finder, System Settings,
Figma, an Electron app with no browser tools.

Two ways to act. `ui_tree` walks the accessibility tree and prints elements
with ids, so a click lands on a button rather than a coordinate that goes stale
when the layout moves. The raw input tools (mouse_*, type_text, press_keys) are
the fallback for anything the tree does not expose.

Events go out through CoreGraphics over ctypes, so the frozen brain does not
need pyobjc or pyautogui. macOS only delivers synthetic events when the app
hosting the brain holds the Accessibility grant, so every tool preflights it
and returns the fix instead of silently doing nothing.

Coordinates are logical points, origin at the top-left of the main display,
y growing downward. `desktop_screenshot` resizes its PNG to the same point
grid, so a pixel the model sees maps 1:1 to a coordinate it can click.
"""

import asyncio
import ctypes
import ctypes.util
import logging
import os
import platform
import re
import time
from pathlib import Path

from camel.toolkits import BaseToolkit, FunctionTool, RegisteredAgentToolkit

from app.agent.toolkit import ax_tree
from app.agent.toolkit.abstract_toolkit import AbstractToolkit
from app.agent.toolkit.app_capture_toolkit import (
    list_windows,
    screen_capture_allowed,
)
from app.utils.listen.toolkit_listen import listen_toolkit

logger = logging.getLogger("desktop_toolkit")

_ACCESSIBILITY_HELP = (
    "macOS silently drops synthetic input, and hides every app's UI tree, until "
    "the app hosting the brain has Accessibility permission. Open System "
    "Settings > Privacy & Security > Accessibility, enable Undisclosed (or the "
    "terminal running the dev brain), then restart the app. Call "
    "request_desktop_permission to open that pane."
)

_SCREEN_RECORDING_HELP = (
    "Screen Recording is not granted for the app hosting the brain: open "
    "System Settings > Privacy & Security > Screen Recording, enable "
    "Undisclosed, then restart the app."
)

# --------------------------------------------------------------- CoreGraphics

# CGEventType
_MOUSE_MOVED = 5
_LEFT_DOWN, _LEFT_UP = 1, 2
_RIGHT_DOWN, _RIGHT_UP = 3, 4
_OTHER_DOWN, _OTHER_UP = 25, 26
_LEFT_DRAGGED, _RIGHT_DRAGGED, _OTHER_DRAGGED = 6, 7, 27
_SCROLL = 22
_HID_TAP = 0
_CLICK_STATE_FIELD = 1
_BUTTON_CODES = {"left": 0, "right": 2, "middle": 1}
_BUTTON_EVENTS = {
    "left": (_LEFT_DOWN, _LEFT_UP, _LEFT_DRAGGED),
    "right": (_RIGHT_DOWN, _RIGHT_UP, _RIGHT_DRAGGED),
    "middle": (_OTHER_DOWN, _OTHER_UP, _OTHER_DRAGGED),
}

# modifier flag masks on CGEventFlags
_MODIFIERS = {
    "cmd": 0x100000,
    "command": 0x100000,
    "shift": 0x20000,
    "ctrl": 0x40000,
    "control": 0x40000,
    "alt": 0x80000,
    "opt": 0x80000,
    "option": 0x80000,
    "fn": 0x800000,
}

# US-layout virtual key codes
_VK = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8,
    "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
    "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25,
    "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, "o": 31, "u": 32, "[": 33,
    "i": 34, "p": 35, "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42,
    ",": 43, "/": 44, "n": 45, "m": 46, ".": 47, "`": 50,
}
_NAMED_KEYS = {
    "return": 36, "enter": 76, "tab": 48, "space": 49, "delete": 51,
    "backspace": 51, "escape": 53, "esc": 53, "forwarddelete": 117,
    "home": 115, "end": 119, "pageup": 116, "pagedown": 121,
    "left": 123, "right": 124, "down": 125, "up": 126,
    **{f"f{i}": code for i, code in enumerate(
        (122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111), start=1
    )},
}


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


_QUARTZ = None


def _quartz():
    """(CoreGraphics, CoreFoundation) with the signatures this module needs."""
    global _QUARTZ
    if _QUARTZ is not None:
        return _QUARTZ

    try:
        lib = ctypes.CDLL(
            ctypes.util.find_library("ApplicationServices")
            or "/System/Library/Frameworks/ApplicationServices.framework/"
            "ApplicationServices"
        )
        cf = ctypes.CDLL(
            ctypes.util.find_library("CoreFoundation")
            or "/System/Library/Frameworks/CoreFoundation.framework/"
            "CoreFoundation"
        )

        lib.CGEventCreate.argtypes = [ctypes.c_void_p]
        lib.CGEventCreate.restype = ctypes.c_void_p
        lib.CGEventCreateMouseEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            _CGPoint,
            ctypes.c_uint32,
        ]
        lib.CGEventCreateMouseEvent.restype = ctypes.c_void_p
        lib.CGEventCreateKeyboardEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint16,
            ctypes.c_bool,
        ]
        lib.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
        lib.CGEventKeyboardSetUnicodeString.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_uint16),
        ]
        lib.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        lib.CGEventSetIntegerValueField.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int64,
        ]
        lib.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        lib.CGEventGetLocation.argtypes = [ctypes.c_void_p]
        lib.CGEventGetLocation.restype = _CGPoint
        lib.CGEventCreateScrollWheelEvent.restype = ctypes.c_void_p
        lib.CGMainDisplayID.restype = ctypes.c_uint32
        lib.CGDisplayBounds.argtypes = [ctypes.c_uint32]
        lib.CGDisplayBounds.restype = _CGRect
        lib.CGDisplayPixelsWide.argtypes = [ctypes.c_uint32]
        lib.CGDisplayPixelsWide.restype = ctypes.c_size_t
        lib.CGDisplayPixelsHigh.argtypes = [ctypes.c_uint32]
        lib.CGDisplayPixelsHigh.restype = ctypes.c_size_t
        lib.CGGetActiveDisplayList.argtypes = [
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        lib.AXIsProcessTrusted.restype = ctypes.c_bool

        cf.CFRelease.argtypes = [ctypes.c_void_p]

        _QUARTZ = (lib, cf)
    except Exception:
        logger.debug("CoreGraphics unavailable for desktop control", exc_info=True)
        _QUARTZ = False
    return _QUARTZ


#Channels that mean someone is sitting at this Mac. The editor panel reports
#"web" because it mounts as an embedded bundle, not because it is remote, so it
#belongs here. Slack/WhatsApp/telegram/remote_control stay out.
LOCAL_CHANNELS: tuple[str, ...] = ("desktop", "web")


def current_channel() -> str:
    """Channel of the turn being run, or 'desktop' when there is no run context."""
    try:
        from app.run_context import get_current_run_context

        context = get_current_run_context()
    except Exception:
        return "desktop"
    if context is None:
        return "desktop"
    return (getattr(context, "channel", "") or "desktop").strip().lower()


def accessibility_trusted() -> bool | None:
    """Whether this process may post synthetic input. None when unknown."""
    libs = _quartz()
    if not libs:
        return None
    try:
        return bool(libs[0].AXIsProcessTrusted())
    except Exception:
        return None


def _release(cf, ref) -> None:
    if ref:
        try:
            cf.CFRelease(ref)
        except Exception:
            pass


# ------------------------------------------------------------------- displays


def displays() -> list[dict]:
    """Active displays with their point bounds and pixel size."""
    libs = _quartz()
    if not libs:
        return []
    lib, _ = libs
    ids = (ctypes.c_uint32 * 8)()
    count = ctypes.c_uint32(0)
    if lib.CGGetActiveDisplayList(8, ids, ctypes.byref(count)) != 0:
        return []

    found = []
    for index in range(count.value):
        display_id = ids[index]
        bounds = lib.CGDisplayBounds(display_id)
        width = int(bounds.size.width)
        height = int(bounds.size.height)
        if not width or not height:
            continue
        pixels_wide = int(lib.CGDisplayPixelsWide(display_id))
        found.append(
            {
                "id": int(display_id),
                "main": display_id == lib.CGMainDisplayID(),
                "origin": [int(bounds.origin.x), int(bounds.origin.y)],
                "points": [width, height],
                "pixels": [pixels_wide, int(lib.CGDisplayPixelsHigh(display_id))],
                "scale": round(pixels_wide / width, 2) if width else 1.0,
            }
        )
    return found


def cursor_position() -> tuple[int, int] | None:
    libs = _quartz()
    if not libs:
        return None
    lib, cf = libs
    event = lib.CGEventCreate(None)
    if not event:
        return None
    try:
        point = lib.CGEventGetLocation(event)
        return int(point.x), int(point.y)
    finally:
        _release(cf, event)


def _post_mouse(event_type: int, x: int, y: int, button: str = "left") -> bool:
    libs = _quartz()
    if not libs:
        return False
    lib, cf = libs
    event = lib.CGEventCreateMouseEvent(
        None, event_type, _CGPoint(float(x), float(y)), _BUTTON_CODES[button]
    )
    if not event:
        return False
    try:
        lib.CGEventPost(_HID_TAP, event)
    finally:
        _release(cf, event)
    return True


def _click(x: int, y: int, button: str, clicks: int) -> None:
    down_type, up_type, _ = _BUTTON_EVENTS[button]
    for click_index in range(1, clicks + 1):
        for event_type in (down_type, up_type):
            libs = _quartz()
            lib, cf = libs
            event = lib.CGEventCreateMouseEvent(
                None, event_type, _CGPoint(float(x), float(y)),
                _BUTTON_CODES[button],
            )
            if event:
                lib.CGEventSetIntegerValueField(
                    event, _CLICK_STATE_FIELD, click_index
                )
                lib.CGEventPost(_HID_TAP, event)
                _release(cf, event)
        if clicks > 1:
            time.sleep(0.08)


def _drag(start: tuple[int, int], end: tuple[int, int], button: str, steps: int = 12) -> None:
    down_type, up_type, dragged_type = _BUTTON_EVENTS[button]
    _post_mouse(down_type, start[0], start[1], button)
    for step in range(1, steps + 1):
        x = start[0] + (end[0] - start[0]) * step // steps
        y = start[1] + (end[1] - start[1]) * step // steps
        _post_mouse(dragged_type, x, y, button)
        time.sleep(0.012)
    _post_mouse(up_type, end[0], end[1], button)


def _scroll(x: int, y: int, vertical: int, horizontal: int) -> None:
    libs = _quartz()
    if not libs:
        return
    lib, cf = libs
    _post_mouse(_MOUSE_MOVED, x, y)
    event = lib.CGEventCreateScrollWheelEvent(None, 1, 2, vertical, horizontal)
    if not event:
        return
    try:
        lib.CGEventPost(_HID_TAP, event)
    finally:
        _release(cf, event)


def _post_key(keycode: int, flags: int, down: bool) -> bool:
    libs = _quartz()
    if not libs:
        return False
    lib, cf = libs
    event = lib.CGEventCreateKeyboardEvent(None, keycode, down)
    if not event:
        return False
    try:
        lib.CGEventSetFlags(event, flags)
        lib.CGEventPost(_HID_TAP, event)
    finally:
        _release(cf, event)
    return True


def _post_text(chunk: str) -> bool:
    libs = _quartz()
    if not libs:
        return False
    lib, cf = libs
    encoded = chunk.encode("utf-16-le")
    units = [
        int.from_bytes(encoded[i : i + 2], "little")
        for i in range(0, len(encoded), 2)
    ]
    buffer = (ctypes.c_uint16 * len(units))(*units)
    posted = False
    for down in (True, False):
        event = lib.CGEventCreateKeyboardEvent(None, 0, down)
        if not event:
            continue
        try:
            lib.CGEventKeyboardSetUnicodeString(event, len(units), buffer)
            lib.CGEventPost(_HID_TAP, event)
            posted = True
        finally:
            _release(cf, event)
    return posted


def parse_keys(combo: str | list[str]) -> tuple[list[str], str]:
    """Split 'cmd+shift+4' (or ['cmd','shift','4']) into modifiers and key."""
    if isinstance(combo, str):
        parts = [part for part in re.split(r"[+\s]+", combo) if part]
    else:
        parts = [str(part) for part in combo if str(part).strip()]
    if not parts:
        raise ValueError("no key given")
    key = parts[-1].strip().lower()
    modifiers = [part.strip().lower() for part in parts[:-1]]
    return modifiers, key


def keycode_for(key: str) -> int | None:
    if len(key) == 1:
        return _VK.get(key)
    return _NAMED_KEYS.get(key)


# --------------------------------------------------------------------- toolkit


class DesktopToolkit(BaseToolkit, RegisteredAgentToolkit, AbstractToolkit):
    """Mouse and keyboard control for native apps on macOS."""

    agent_name: str

    @classmethod
    def toolkit_name(cls) -> str:
        return "Desktop Control"

    @classmethod
    def available(cls) -> bool:
        """Whether this host can post input events at all."""
        return platform.system() == "Darwin" and bool(_quartz())

    def __init__(
        self,
        api_task_id: str,
        agent_name: str = "Single Agent",
        working_directory: str | None = None,
        timeout: float | None = 120,
        shot_dir: str | None = None,
    ):
        BaseToolkit.__init__(self, timeout)
        RegisteredAgentToolkit.__init__(self)
        self.api_task_id = api_task_id
        self.agent_name = agent_name
        self.working_directory = working_directory or os.getcwd()
        self.shot_dir = shot_dir or self.working_directory
        #Element ids only mean something within the snapshot that produced them.
        self._ax_rows: list[dict] = []
        self._ax_index: dict[str, dict] = {}
        self._ax_snapshot = 0

    # ------------------------------------------------------------------ tools

    def get_tools(self) -> list[FunctionTool]:
        return [
            FunctionTool(self.desktop_status),
            FunctionTool(self.desktop_screenshot),
            FunctionTool(self.list_desktop_apps),
            FunctionTool(self.activate_app),
            FunctionTool(self.ui_tree),
            FunctionTool(self.element_at),
            FunctionTool(self.click_element),
            FunctionTool(self.set_element_value),
            FunctionTool(self.mouse_move),
            FunctionTool(self.mouse_click),
            FunctionTool(self.mouse_drag),
            FunctionTool(self.mouse_scroll),
            FunctionTool(self.type_text),
            FunctionTool(self.press_keys),
            FunctionTool(self.request_desktop_permission),
        ]

    def _blocked(self) -> str | None:
        #re-check the channel at call time: an agent built during a desktop turn
        #can be resumed by a Slack follow-up, and the toolkit would still be here
        channel = current_channel()
        if channel not in LOCAL_CHANNELS:
            return (
                f"Desktop Control only runs for turns started on this machine; "
                f"this turn came from {channel}. Ask the user to do it there."
            )
        if platform.system() != "Darwin":
            return (
                "Desktop Control needs macOS today; this host is "
                f"{platform.system()}. Use the browser tools for web tasks."
            )
        if not _quartz():
            return "CoreGraphics is unavailable, so input events cannot be sent."
        if accessibility_trusted() is False:
            return f"Accessibility permission is not granted. {_ACCESSIBILITY_HELP}"
        return None

    @listen_toolkit()
    async def desktop_status(self) -> str:
        r"""Check whether the agent can drive the desktop, and in what space.

        Call this before the first click. It reports the Accessibility grant,
        the displays and their scale factor, and where the pointer is.

        Returns:
            A status block: permission, displays in logical points and pixels,
            cursor position, and the frontmost app.
        """
        lines: list[str] = []

        if platform.system() != "Darwin":
            return (
                f"Desktop Control is not available on {platform.system()}. "
                "The browser tools cover web pages; there is no native-input "
                "backend for this platform yet."
            )

        trusted = accessibility_trusted()
        if trusted is True:
            lines.append("Accessibility: granted, input events will be delivered.")
        elif trusted is False:
            lines.append(f"Accessibility: NOT granted. {_ACCESSIBILITY_HELP}")
        else:
            lines.append("Accessibility: unknown (CoreGraphics did not report).")

        screens = displays()
        for screen in screens:
            lines.append(
                f"Display {screen['id']}"
                f"{' (main)' if screen['main'] else ''}: "
                f"{screen['points'][0]}x{screen['points'][1]} points, "
                f"{screen['pixels'][0]}x{screen['pixels'][1]} px, "
                f"scale {screen['scale']}x, origin {screen['origin']}"
            )
        if not screens:
            lines.append("Displays: none reported.")

        position = cursor_position()
        if position:
            lines.append(f"Cursor: {position[0]}, {position[1]} (points)")

        front = self._frontmost_app()
        if front:
            lines.append(f"Frontmost app: {front}")

        lines.append(
            "Coordinates are logical points from the top-left of the main "
            "display. desktop_screenshot returns a PNG on that same point grid."
        )
        return "\n".join(lines)

    @listen_toolkit()
    async def desktop_screenshot(
        self,
        region: str = "",
        out: str = "",
    ) -> str:
        r"""Capture the screen (or a region) to a PNG for the agent to look at.

        The image is written at logical point size, so a pixel you see in it
        is the exact coordinate to pass to mouse_click. Pass the file to
        read_image (Image Reader) to actually see it.

        Args:
            region (str): Optional "x,y,width,height" in points, e.g.
                "0,0,800,600" for a corner. Empty captures the whole main
                display.
            out (str): Optional output path. Defaults to the working
                directory with a timestamped name.

        Returns:
            The saved path, the image size, and the region it covers.
        """
        #a screenshot only needs Screen Recording; looking must work before the
        #agent is allowed to act, so this deliberately skips the input guard
        if platform.system() != "Darwin":
            return f"Desktop screenshots need macOS; this host is {platform.system()}."

        path = Path(out).expanduser() if out else Path(
            self.shot_dir
        ) / f"desktop-{int(time.time())}.png"
        path.parent.mkdir(parents=True, exist_ok=True)

        args = ["-x", "-o"]
        area = None
        if region:
            try:
                area = [int(part) for part in region.split(",")]
                if len(area) != 4:
                    raise ValueError
            except ValueError:
                return 'region must be "x,y,width,height" in points, e.g. "0,0,800,600".'
            args += ["-R", ",".join(str(value) for value in area)]
        else:
            #only the main display, not the whole virtual desktop
            main = next((s for s in displays() if s["main"]), None)
            if main:
                area = [*main["origin"], *main["points"]]
                args += ["-R", ",".join(str(value) for value in area)]

        code, _, err = await self._run(["/usr/sbin/screencapture", *args, str(path)])
        if code != 0 or not path.is_file():
            reason = err.decode("utf-8", "replace").strip() or f"exit {code}"
            if screen_capture_allowed() is False:
                reason += f" {_SCREEN_RECORDING_HELP}"
            return f"screencapture failed: {reason}"

        width, height = (area[2], area[3]) if area else (None, None)
        try:
            from PIL import Image

            with Image.open(path) as image:
                pixels = image.size
                if width and height and image.size != (width, height):
                    image = image.resize(
                        (width, height), Image.Resampling.LANCZOS
                    )
                    image.save(path, format="PNG")
        except Exception:
            logger.debug("desktop screenshot resize skipped", exc_info=True)
            pixels = None

        size_text = f"{width}x{height} points" if width else "full display"
        detail = f"{path} ({size_text}"
        if pixels:
            detail += f", captured at {pixels[0]}x{pixels[1]} px"
        detail += (
            "). A pixel in this PNG is a coordinate you can click. Read it with "
            "read_image before clicking."
        )
        if screen_capture_allowed() is False:
            detail += (
                " NOTE: Screen Recording is not granted, so the image may be "
                "wallpaper only. Enable it for the app hosting the brain."
            )
        return detail

    @listen_toolkit()
    async def list_desktop_apps(self) -> str:
        r"""List visible app windows, front to back, with their bounds.

        Use this to find an app to activate or a window to aim at before
        taking a screenshot. Bounds are in points.

        Returns:
            One line per visible window: app, title, window number, bounds.
        """
        if platform.system() != "Darwin":
            return f"Window listing needs macOS; this host is {platform.system()}."

        windows = list_windows()
        if not windows:
            return "No visible app windows reported."

        seen: dict[str, list[dict]] = {}
        for window in windows:
            seen.setdefault(window["owner"], []).append(window)

        lines = [f"Visible windows ({len(windows)}), front to back:"]
        for owner, entries in seen.items():
            lines.append(f"- {owner}")
            for entry in entries:
                title = f'"{entry["title"]}"' if entry["title"] else "(untitled)"
                bounds = entry["bounds"]
                area = (
                    f"{int(bounds[0])},{int(bounds[1])} "
                    f"{int(bounds[2])}x{int(bounds[3])}"
                    if bounds
                    else "bounds unknown"
                )
                lines.append(
                    f"    {title} window {entry['number']} at {area}"
                )
        return "\n".join(lines)

    @listen_toolkit()
    async def activate_app(self, app: str) -> str:
        r"""Bring an app to the front so the next click lands on it.

        Args:
            app (str): App name as macOS knows it, e.g. "Finder", "Notes",
                "System Settings".

        Returns:
            Whether it became frontmost, and what is frontmost now.
        """
        blocked = self._blocked()
        if blocked:
            return blocked

        code, _, err = await self._run(["open", "-a", app])
        if code != 0:
            return (
                f"Could not open {app!r}: "
                + (err.decode("utf-8", "replace").strip() or f"exit {code}")
            )

        await asyncio.sleep(0.6)
        front = self._frontmost_app()
        if front and front.lower() != app.lower():
            return (
                f"Requested {app!r}; frontmost is now {front!r}. If that is "
                "the wrong app, pass its exact name from list_desktop_apps."
            )
        return f"{front or app} is frontmost."

    @listen_toolkit()
    async def ui_tree(
        self,
        app: str = "",
        depth: int = 8,
        max_nodes: int = 150,
        query: str = "",
    ) -> str:
        r"""Read an app's UI tree: every element with a role, label and frame.

        This is the element-level alternative to guessing coordinates. Prefer
        it over mouse_click whenever you can name what you want to press,
        because frames are resolved from the live layout.

        Args:
            app (str): App name from list_desktop_apps, or a pid. Empty reads
                the frontmost app.
            depth (int): How deep to descend. 8 covers most apps; lower it to
                make the output smaller.
            max_nodes (int): Stop after this many elements.
            query (str): Optional case-insensitive filter over role, label,
                value and identifier, e.g. "save" or "AXTextField".

        Returns:
            An indented tree where each line starts with an element id, e.g.
            `s2e14 AXButton "Save" @ 812,64 74x28 actions=AXPress`. Pass those
            ids to click_element or set_element_value. Ids expire on the next
            ui_tree or element_at call.
        """
        blocked = self._ax_blocked()
        if blocked:
            return blocked

        pid, owner, error = ax_tree.resolve_target(app, list_windows())
        if error or pid is None:
            return error or "Could not resolve that app."

        try:
            depth = max(1, min(int(depth or 8), 20))
            max_nodes = max(10, min(int(max_nodes or 150), 400))
        except (TypeError, ValueError):
            return "depth and max_nodes must be whole numbers."

        rows, walk_error = await asyncio.to_thread(
            ax_tree.snapshot,
            pid,
            max_depth=depth,
            max_nodes=max_nodes,
            query=query,
        )
        if not rows:
            self._forget_tree()
            return f"{owner} (pid {pid}): {walk_error}"

        prefix = self._remember_tree(rows)
        lines = ax_tree.format_tree(rows, prefix=prefix)
        header = (
            f"{owner} (pid {pid}): {len(rows)} elements. Press one with "
            f'click_element("{prefix}1"), or type into it with '
            f'set_element_value("{prefix}1", "text").'
        )
        return "\n".join(
            [
                header,
                *lines,
                "Frames are logical points. Ids are only valid until the next "
                "ui_tree; re-read the tree after anything that changes the "
                "screen.",
            ]
        )

    @listen_toolkit()
    async def element_at(self, x: int, y: int) -> str:
        r"""Identify the interactive element under a screen point.

        Use this when you can see a control in a screenshot but do not want to
        guess which tree node it is: pass the pixel you would have clicked and
        get the element back.

        Args:
            x (int): Horizontal position in logical points.
            y (int): Vertical position in logical points.

        Returns:
            The element's id, role, label and frame, ready for click_element.
        """
        blocked = self._ax_blocked()
        if blocked:
            return blocked

        node, error = await asyncio.to_thread(
            ax_tree.element_at, int(x), int(y)
        )
        if error or not node:
            return error or f"No element at {int(x)}, {int(y)}."

        prefix = self._remember_tree([node])
        owner = next(
            (
                window.get("owner")
                for window in list_windows()
                if window.get("pid") == node.get("pid")
            ),
            None,
        )
        line = ax_tree.format_row(node, f"{prefix}1")
        place = f" in {owner}" if owner else ""
        return (
            f"{line}\n"
            f"Element {prefix}1{place}. Act on it with click_element, or type "
            "into it with set_element_value."
        )

    @listen_toolkit()
    async def click_element(self, element_id: str, action: str = "") -> str:
        r"""Press an element from the last ui_tree or element_at.

        With an action available on the element this fires the accessibility
        action instead of a synthetic click, so it works even when the element
        is partly covered.

        Args:
            element_id (str): Id printed by ui_tree or element_at, e.g. "s2e14".
            action (str): Optional. "auto" (default) presses the element or
                clicks its centre; "click" always posts a real mouse click at
                the centre; any other value is an accessibility action name
                such as "AXShowMenu".

        Returns:
            What was pressed, and how.
        """
        blocked = self._blocked()
        if blocked:
            return blocked

        row, error = self._lookup(element_id)
        if row is None:
            return error

        label = ax_tree.format_row(row)
        wanted = (action or "").strip()

        if wanted.lower() in ("click", "mouse"):
            return await self._click_center(row, label)

        if not wanted or wanted.lower() == "auto":
            if "AXPress" in (row.get("actions") or []):
                code = await asyncio.to_thread(
                    ax_tree.perform, row["ref"], "AXPress"
                )
                if code == ax_tree.ERR_SUCCESS:
                    await asyncio.sleep(0.25)
                    return (
                        f"Pressed {label} via AXPress. Re-run ui_tree before "
                        "the next action if the screen changed."
                    )
                logger.debug("AXPress failed on %s: %s", label, code)
            return await self._click_center(row, label)

        code = await asyncio.to_thread(ax_tree.perform, row["ref"], wanted)
        if code != ax_tree.ERR_SUCCESS:
            available = ", ".join(row.get("actions") or []) or "none"
            return (
                f"{label} could not run {wanted!r}: "
                f"{ax_tree.error_text(code)}. Actions here: {available}."
            )
        await asyncio.sleep(0.25)
        return f"Ran {wanted} on {label}."

    @listen_toolkit()
    async def set_element_value(self, element_id: str, text: str) -> str:
        r"""Write text straight into a field, without clicking or key events.

        Works on text fields, text areas and other elements that expose a
        writable AXValue. Focus is handled by the app, so nothing can steal
        the keystrokes midway.

        Args:
            element_id (str): Id printed by ui_tree or element_at.
            text (str): The value to write. Empty string clears the field.

        Returns:
            Confirmation, or what to do instead when the element is not
            writable.
        """
        blocked = self._blocked()
        if blocked:
            return blocked

        row, error = self._lookup(element_id)
        if row is None:
            return error

        label = ax_tree.format_row(row)
        code = await asyncio.to_thread(ax_tree.set_value, row["ref"], text)
        if code == ax_tree.ERR_SUCCESS:
            await asyncio.sleep(0.15)
            return f"Set {label} to {text!r}."
        hint = ""
        if code in (
            ax_tree.ERR_UNSUPPORTED_ATTRIBUTE,
            ax_tree.ERR_INVALID_ELEMENT,
        ):
            hint = " Focus it and type instead: click_element, then type_text."
        return (
            f"Could not write into {label}: {ax_tree.error_text(code)}.{hint}"
        )

    @listen_toolkit()
    async def mouse_move(self, x: int, y: int) -> str:
        r"""Move the pointer to a point without clicking.

        Args:
            x (int): Horizontal position in logical points from the left edge.
            y (int): Vertical position in logical points from the top edge.

        Returns:
            Confirmation with the new cursor position.
        """
        blocked = self._blocked()
        if blocked:
            return blocked
        if not _post_mouse(_MOUSE_MOVED, int(x), int(y)):
            return "Could not post the mouse-move event."
        await asyncio.sleep(0.1)
        return f"Pointer moved to {int(x)}, {int(y)}."

    @listen_toolkit()
    async def mouse_click(
        self,
        x: int | None = None,
        y: int | None = None,
        button: str = "left",
        clicks: int = 1,
    ) -> str:
        r"""Click at a point (or wherever the pointer is when x/y are omitted).

        Args:
            x (int): Horizontal position in points. Omit to click in place.
            y (int): Vertical position in points. Omit to click in place.
            button (str): "left", "right" or "middle".
            clicks (int): 1 for a click, 2 for a double-click.

        Returns:
            Confirmation of what was clicked.
        """
        blocked = self._blocked()
        if blocked:
            return blocked
        button = (button or "left").lower()
        if button not in _BUTTON_EVENTS:
            return 'button must be "left", "right" or "middle".'
        if (x is None) != (y is None):
            return "Pass both x and y, or neither to click in place."
        clicks = max(1, min(int(clicks or 1), 3))

        if x is None or y is None:
            position = cursor_position()
            if not position:
                return "Could not read the cursor position; pass x and y."
            x, y = position

        _post_mouse(_MOUSE_MOVED, int(x), int(y))
        await asyncio.sleep(0.06)
        await asyncio.to_thread(_click, int(x), int(y), button, clicks)
        await asyncio.sleep(0.15)
        label = "double-click" if clicks == 2 else f"{button} click"
        return f"{label} at {int(x)}, {int(y)}."

    @listen_toolkit()
    async def mouse_drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        button: str = "left",
    ) -> str:
        r"""Press, drag and release between two points.

        Args:
            start_x (int): Where to press, in points.
            start_y (int): Where to press, in points.
            end_x (int): Where to release, in points.
            end_y (int): Where to release, in points.
            button (str): "left", "right" or "middle".

        Returns:
            Confirmation of the drag.
        """
        blocked = self._blocked()
        if blocked:
            return blocked
        button = (button or "left").lower()
        if button not in _BUTTON_EVENTS:
            return 'button must be "left", "right" or "middle".'
        await asyncio.to_thread(
            _drag,
            (int(start_x), int(start_y)),
            (int(end_x), int(end_y)),
            button,
        )
        await asyncio.sleep(0.15)
        return (
            f"Dragged {button} button from {int(start_x)}, {int(start_y)} to "
            f"{int(end_x)}, {int(end_y)}."
        )

    @listen_toolkit()
    async def mouse_scroll(
        self,
        vertical: int,
        horizontal: int = 0,
        x: int | None = None,
        y: int | None = None,
    ) -> str:
        r"""Scroll the view under the pointer.

        Args:
            vertical (int): Lines to scroll. Positive scrolls up, negative
                down; 3 to 5 is a comfortable nudge.
            horizontal (int): Lines to scroll sideways, positive right.
            x (int): Move here first, in points. Omit to stay put.
            y (int): Move here first, in points. Omit to stay put.

        Returns:
            Confirmation of the scroll.
        """
        blocked = self._blocked()
        if blocked:
            return blocked
        if x is None or y is None:
            position = cursor_position()
            if not position:
                return "Could not read the cursor position; pass x and y."
            x, y = position
        await asyncio.to_thread(
            _scroll, int(x), int(y), int(vertical or 0), int(horizontal or 0)
        )
        await asyncio.sleep(0.15)
        return (
            f"Scrolled {int(vertical or 0)} lines vertically, "
            f"{int(horizontal or 0)} horizontally at {int(x)}, {int(y)}."
        )

    @listen_toolkit()
    async def type_text(self, text: str) -> str:
        r"""Type text into the focused field, including unicode.

        Click the field first. Unicode is sent as text, not keycodes, so
        emoji and accents work without a keyboard layout change.

        Args:
            text (str): The text to type. Newlines are sent as Return.

        Returns:
            Confirmation with the number of characters typed.
        """
        blocked = self._blocked()
        if blocked:
            return blocked
        if not text:
            return "Nothing to type: text was empty."

        typed = 0
        for line_index, line in enumerate(text.split("\n")):
            if line_index:
                await asyncio.to_thread(_post_key, 36, 0, True)
                await asyncio.to_thread(_post_key, 36, 0, False)
                typed += 1
                await asyncio.sleep(0.02)
            for start in range(0, len(line), 10):
                chunk = line[start : start + 10]
                if await asyncio.to_thread(_post_text, chunk):
                    typed += len(chunk)
                await asyncio.sleep(0.02)
        await asyncio.sleep(0.15)
        return f"Typed {typed} characters."

    @listen_toolkit()
    async def press_keys(self, keys: str | list[str]) -> str:
        r"""Press a key or a chord, e.g. "cmd+s", "cmd+shift+4", "enter".

        Modifiers come first and are held for the final key. Key names are
        US layout letters/digits/symbols, or one of: return, enter, tab,
        space, escape, delete, forwarddelete, home, end, pageup, pagedown,
        left, right, up, down, f1 to f12.

        Args:
            keys (str | list[str]): "cmd+s" or ["cmd", "shift", "4"].

        Returns:
            Confirmation of the chord that was pressed.
        """
        blocked = self._blocked()
        if blocked:
            return blocked

        try:
            modifiers, key = parse_keys(keys)
        except ValueError as exc:
            return str(exc)

        unknown = [name for name in modifiers if name not in _MODIFIERS]
        if unknown:
            return (
                f"Unknown modifier(s) {unknown}. Use cmd, shift, ctrl, alt/option."
            )
        code = keycode_for(key)
        if code is None:
            if len(key) > 1:
                return f"Unknown key {key!r}. Use a letter, digit or a named key."
            #a symbol outside the map: type it instead of pressing a keycode
            if await asyncio.to_thread(_post_text, key):
                return f"Typed {key!r}."

        flags = 0
        for name in modifiers:
            flags |= _MODIFIERS[name]

        await asyncio.to_thread(_post_key, code, flags, True)
        await asyncio.sleep(0.04)
        await asyncio.to_thread(_post_key, code, flags, False)
        await asyncio.sleep(0.12)
        chord = "+".join([*modifiers, key])
        return f"Pressed {chord}."

    @listen_toolkit()
    async def request_desktop_permission(self) -> str:
        r"""Ask macOS for the Accessibility grant this toolkit needs.

        Call this when desktop_status reports the grant is missing. macOS shows
        its own prompt; in a dev build you may have to add the binary by hand
        in System Settings > Privacy & Security > Accessibility.

        Returns:
            Whether the grant is now in place, plus what to do if it is not.
        """
        if platform.system() != "Darwin":
            return f"Nothing to grant: this host is {platform.system()}."

        libs = _quartz()
        if not libs:
            return "CoreGraphics is unavailable, so the grant cannot be checked."
        lib, cf = libs

        prompted = False
        try:
            lib.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
            lib.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
            prompt_key = ctypes.c_void_p.in_dll(
                lib, "kAXTrustedCheckOptionPrompt"
            )
            true_value = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue")
            keys = (ctypes.c_void_p * 1)(prompt_key)
            values = (ctypes.c_void_p * 1)(true_value)
            cf.CFDictionaryCreate.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.POINTER(ctypes.c_void_p),
                ctypes.c_long,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ]
            cf.CFDictionaryCreate.restype = ctypes.c_void_p
            options = cf.CFDictionaryCreate(
                None,
                keys,
                values,
                1,
                ctypes.c_void_p.in_dll(cf, "kCFTypeDictionaryKeyCallBacks"),
                ctypes.c_void_p.in_dll(cf, "kCFTypeDictionaryValueCallBacks"),
            )
            if options:
                try:
                    lib.AXIsProcessTrustedWithOptions(options)
                    prompted = True
                finally:
                    _release(cf, options)
        except Exception:
            logger.debug("accessibility prompt failed", exc_info=True)

        if accessibility_trusted():
            return "Accessibility is granted; desktop input will work now."

        await self._run(
            [
                "open",
                "x-apple.systempreferences:com.apple.preference.security"
                "?Privacy_Accessibility",
            ]
        )
        prefix = "Asked macOS to prompt. " if prompted else ""
        return (
            f"{prefix}Accessibility is still not granted. In the pane that "
            "just opened, add the app that hosts the brain (Undisclosed, or "
            "your terminal for a dev brain), enable it, then restart the app."
        )

    # ----------------------------------------------------------------- helpers

    def _ax_blocked(self) -> str | None:
        blocked = self._blocked()
        if blocked:
            return blocked
        if not ax_tree.available():
            return (
                "The accessibility bridge could not load on this host, so the "
                "UI tree is unavailable. Fall back to desktop_screenshot plus "
                "mouse_click."
            )
        return None

    def _remember_tree(self, rows: list[dict]) -> str:
        """Adopt a snapshot and return the id prefix for its elements."""
        self._forget_tree()
        self._ax_snapshot += 1
        prefix = f"s{self._ax_snapshot}e"
        self._ax_index = {
            f"{prefix}{index}": row for index, row in enumerate(rows, start=1)
        }
        self._ax_rows = rows
        return prefix

    def _forget_tree(self) -> None:
        ax_tree.release_nodes(self._ax_rows)
        self._ax_rows = []
        self._ax_index = {}

    def _lookup(self, element_id: str) -> tuple[dict | None, str]:
        key = (element_id or "").strip()
        row = self._ax_index.get(key)
        if row is not None:
            return row, ""
        if key and not key.startswith(f"s{self._ax_snapshot}e"):
            return None, (
                f"{key!r} came from an older snapshot. Call ui_tree again and "
                "use the ids it prints."
            )
        return None, (
            f"Unknown element id {element_id!r}. Call ui_tree (or element_at) "
            "first."
        )

    async def _click_center(self, row: dict, label: str) -> str:
        point = ax_tree.center(row.get("frame"))
        if point is None:
            return (
                f"{label} has no on-screen frame, so there is nothing to "
                "click. It may be collapsed or scrolled out of view."
            )
        await asyncio.to_thread(_click, point[0], point[1], "left", 1)
        await asyncio.sleep(0.2)
        return f"Clicked {label} at {point[0]}, {point[1]}."

    def _frontmost_app(self) -> str:
        windows = list_windows()
        return windows[0]["owner"] if windows else ""

    async def _run(
        self, args: list[str], timeout: float = 30
    ) -> tuple[int, bytes, bytes]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            return -1, b"", str(exc).encode()

        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return -1, b"", f"timed out after {int(timeout)}s".encode()
        code = proc.returncode if proc.returncode is not None else -1
        return code, out or b"", err or b""
