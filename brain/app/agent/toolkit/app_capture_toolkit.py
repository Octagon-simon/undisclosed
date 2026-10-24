# Copyright (c) 2026 Simon Ugorji
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""App camera: screenshot a running app instead of a URL.

The page camera covers rendered web pages in Chrome. This covers the other
half of "look at it": a native app window on macOS, a booted iOS Simulator, or
an Android device or emulator.

Mobile targets are read straight off the framebuffer (`simctl` / `adb`), so
they need no Screen Recording permission. macOS window capture does need it,
because the pixels belong to another process.
"""

import asyncio
import json
import logging
import os
import platform
import re
import shutil
from pathlib import Path

from camel.toolkits import BaseToolkit, FunctionTool, RegisteredAgentToolkit
from camel.utils.tool_result import ToolResult

from app.agent.toolkit.abstract_toolkit import AbstractToolkit
from app.agent.toolkit.shot_vision import (
    READ_PROMPT,
    agent_sees_images,
    describe_images,
    image_size,
    load_images,
)
from app.component.environment import env
from app.utils.listen.toolkit_listen import listen_toolkit

logger = logging.getLogger("app_capture_toolkit")

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_SAFE_CAPTURE_SECONDS = 90

_TCC_HELP = (
    "macOS blocks window capture until the app that hosts the brain has Screen "
    "Recording permission. Open System Settings > Privacy & Security > Screen "
    "Recording, enable Undisclosed, then restart the app. For an app running in "
    "the iOS Simulator or an Android emulator this is not needed at all: "
    "capture that target instead."
)


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "app"


# --------------------------------------------------------------- process I/O


async def _run(args: list[str], timeout: float = 30) -> tuple[int, bytes, bytes]:
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
    return proc.returncode, out or b"", err or b""


def _screencapture_binary() -> str | None:
    #macOS keeps it at /usr/sbin, which is not always on PATH
    return shutil.which("screencapture") or (
        "/usr/sbin/screencapture"
        if Path("/usr/sbin/screencapture").is_file()
        else None
    )


# ---------------------------------------------------- macOS window enumeration

_CG_STATE: tuple | bool | None = None

_CG_STRING_KEYS = (
    "kCGWindowNumber",
    "kCGWindowOwnerName",
    "kCGWindowName",
    "kCGWindowLayer",
    "kCGWindowOwnerPID",
    "kCGWindowBounds",
    "X",
    "Y",
    "Width",
    "Height",
)


def _cg():
    """(CoreGraphics, CoreFoundation, key refs) or False when unavailable.

    CoreGraphics is reached over ctypes instead of pulling pyobjc into the
    frozen brain: we only need the window list, not a Foundation bridge.
    """
    global _CG_STATE
    if _CG_STATE is not None:
        return _CG_STATE

    try:
        import ctypes
        import ctypes.util

        cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
        cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))

        cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
        cf.CFArrayGetCount.restype = ctypes.c_long
        cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
        cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
        cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        cf.CFDictionaryGetValue.restype = ctypes.c_void_p
        cf.CFStringGetCString.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_long,
            ctypes.c_uint32,
        ]
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFNumberGetValue.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        cf.CFNumberGetValue.restype = ctypes.c_bool
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        cf.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_uint32,
        ]
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p

        cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
        try:
            cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        except AttributeError:
            pass

        keys = {
            name: cf.CFStringCreateWithCString(None, name.encode(), 0x08000100)
            for name in _CG_STRING_KEYS
        }
        _CG_STATE = (cg, cf, keys)
    except Exception:
        logger.debug("CoreGraphics unavailable for window listing", exc_info=True)
        _CG_STATE = False
    return _CG_STATE


def _cf_string(cf, ref) -> str:
    if not ref:
        return ""
    buf = _cf_buf()
    if cf.CFStringGetCString(ref, buf, len(buf), 0x08000100):
        return buf.value.decode("utf-8", "replace")
    return ""


def _cf_buf():
    import ctypes

    return ctypes.create_string_buffer(1024)


def _cf_number(cf, ref) -> float | None:
    if not ref:
        return None
    import ctypes

    value = ctypes.c_double()
    if cf.CFNumberGetValue(ref, 13, ctypes.byref(value)):  # kCFNumberDoubleType
        return value.value
    return None


def screen_capture_allowed() -> bool | None:
    """Preflight for the Screen Recording grant. None when unknown."""
    libs = _cg()
    if not libs:
        return None
    cg, _, _ = libs
    try:
        return bool(cg.CGPreflightScreenCaptureAccess())
    except AttributeError:
        return None


def list_windows() -> list[dict]:
    """On-screen normal-layer windows: pid, owner, title, number, bounds.

    Window titles are empty when the caller has no Screen Recording grant;
    owners and PIDs still come back, so target discovery keeps working.
    """
    libs = _cg()
    if not libs:
        return []
    cg, cf, keys = libs
    arr = cg.CGWindowListCopyWindowInfo(1 | 16, 0)  # OnScreenOnly + no desktop
    if not arr:
        return []

    windows: list[dict] = []
    try:
        for index in range(cf.CFArrayGetCount(arr)):
            entry = cf.CFArrayGetValueAtIndex(arr, index)

            def get(key: str):
                return cf.CFDictionaryGetValue(entry, keys[key])

            layer = _cf_number(cf, get("kCGWindowLayer"))
            if layer != 0:
                continue
            owner = _cf_string(cf, get("kCGWindowOwnerName"))
            if not owner:
                continue
            number = _cf_number(cf, get("kCGWindowNumber"))
            pid = _cf_number(cf, get("kCGWindowOwnerPID"))
            bounds = None
            bounds_ref = get("kCGWindowBounds")
            if bounds_ref:
                dims = [
                    _cf_number(
                        cf,
                        cf.CFDictionaryGetValue(bounds_ref, keys[axis]),
                    )
                    for axis in ("X", "Y", "Width", "Height")
                ]
                if all(dim is not None for dim in dims):
                    bounds = tuple(dims)
            windows.append(
                {
                    "number": int(number) if number else None,
                    "pid": int(pid) if pid else None,
                    "owner": owner,
                    "title": _cf_string(cf, get("kCGWindowName")),
                    "bounds": bounds,
                }
            )
    finally:
        cf.CFRelease(arr)
    return windows


# ----------------------------------------------------------- mobile listings


def _adb_binary() -> str | None:
    found = shutil.which("adb")
    if found:
        return found
    candidates = [
        Path.home() / "Library" / "Android" / "sdk" / "platform-tools" / "adb",
        Path(os.environ.get("ANDROID_HOME", "")) / "platform-tools" / "adb",
        Path(os.environ.get("ANDROID_SDK_ROOT", "")) / "platform-tools" / "adb",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


async def list_android_devices() -> list[dict]:
    adb = _adb_binary()
    if not adb:
        return []
    code, out, err = await _run([adb, "devices", "-l"], timeout=15)
    if code != 0:
        logger.debug("adb devices failed: %s", err.decode("utf-8", "replace"))
        return []

    devices: list[dict] = []
    for line in out.decode("utf-8", "replace").splitlines()[1:]:
        line = line.strip()
        if not line or "\t" not in line:
            continue
        serial, rest = line.split("\t", 1)
        state = rest.split()[0] if rest.split() else ""
        if state != "device":
            continue
        model = ""
        for part in rest.split():
            if part.startswith("model:"):
                model = part.split(":", 1)[1]
        devices.append(
            {
                "serial": serial.strip(),
                "model": model,
                "emulator": serial.startswith("emulator-"),
            }
        )
    return devices


async def list_simulators() -> list[dict]:
    if not shutil.which("xcrun"):
        return []
    code, out, _err = await _run(
        ["xcrun", "simctl", "list", "devices", "booted", "-j"], timeout=20
    )
    if code != 0:
        return []
    try:
        payload = json.loads(out.decode("utf-8", "replace") or "{}")
    except ValueError:
        return []

    simulators: list[dict] = []
    for runtime, devices in (payload.get("devices") or {}).items():
        for device in devices or []:
            if device.get("state") != "Booted":
                continue
            simulators.append(
                {
                    "udid": device.get("udid", ""),
                    "name": device.get("name", "simulator"),
                    "runtime": str(runtime).rsplit(".", 1)[-1],
                }
            )
    return simulators


# ------------------------------------------------------------------ toolkit


class AppCaptureToolkit(BaseToolkit, RegisteredAgentToolkit, AbstractToolkit):
    agent_name: str

    @classmethod
    def toolkit_name(cls) -> str:
        return "App Screenshots"

    @classmethod
    def available_backends(cls) -> list[str]:
        """Capture backends that can actually write a file on this host."""
        backends: list[str] = []
        if platform.system() == "Darwin" and _screencapture_binary():
            backends.append("window")
        if shutil.which("xcrun"):
            backends.append("simulator")
        if _adb_binary():
            backends.append("android")
        return backends

    def __init__(
        self,
        api_task_id: str,
        agent_name: str = "Single Agent",
        working_directory: str | None = None,
        timeout: float | None = 180,
        shot_dir: str | None = None,
        model_type: str | None = None,
        model_platform: str | None = None,
    ):
        BaseToolkit.__init__(self, timeout)
        RegisteredAgentToolkit.__init__(self)
        self.api_task_id = api_task_id
        self.agent_name = agent_name
        self.working_directory = working_directory or os.getcwd()
        self.shot_dir = shot_dir or env("APP_SHOT_DIR", "") or ""
        self.model_type = model_type
        self.model_platform = model_platform

    # ------------------------------------------------------------------ tools

    def get_tools(self) -> list[FunctionTool]:
        return [
            FunctionTool(self.capture_app),
            FunctionTool(self.list_capture_targets),
        ]

    @listen_toolkit()
    async def list_capture_targets(self) -> str:
        r"""List the apps, simulators and devices that can be captured now.

        Call this first when you do not know the exact app name or which
        simulator or device is running. It returns the names this toolkit
        accepts as `target` for `capture_app`.

        Returns:
            A readable list grouped by backend (macOS windows, iOS
            Simulators, Android devices), or a note when a backend is
            unavailable and why.
        """
        return await self._targets_text()

    async def _targets_text(self) -> str:
        """The listing behind `list_capture_targets`, usable from other tools.

        Kept separate so `_resolve` can quote the list without re-entering the
        tool wrapper (which would emit a second activate/deactivate pair).
        """
        lines: list[str] = []

        if platform.system() == "Darwin":
            windows = list_windows()
            if windows:
                allowed = screen_capture_allowed()
                header = "macOS windows (target: owner name, window title, or window number)"
                if allowed is False:
                    header += " [Screen Recording NOT granted, capture will fail]"
                lines.append(header)
                for window in windows:
                    bits = [f"- {window['owner']}"]
                    if window["title"]:
                        bits.append(f'"{window["title"]}"')
                    if window["number"] is not None:
                        bits.append(f"(window {window['number']}, pid {window['pid']})")
                    lines.append(" ".join(bits))
            else:
                lines.append("macOS windows: none visible (or not running on macOS).")

        simulators = await list_simulators()
        if shutil.which("xcrun"):
            if simulators:
                lines.append("iOS Simulators (target: device name or UDID)")
                for sim in simulators:
                    lines.append(f"- {sim['name']} ({sim['runtime']}, {sim['udid']})")
            else:
                lines.append("iOS Simulators: none booted.")
        else:
            lines.append("iOS Simulators: xcrun not available on this host.")

        devices = await list_android_devices()
        if _adb_binary():
            if devices:
                lines.append("Android devices (target: serial)")
                for device in devices:
                    kind = "emulator" if device["emulator"] else "device"
                    label = device["model"] or device["serial"]
                    lines.append(f"- {device['serial']} ({kind}, {label})")
            else:
                lines.append("Android devices: none attached.")
        else:
            lines.append("Android devices: adb not found on this host.")

        return "\n".join(lines)

    @listen_toolkit()
    async def capture_app(
        self,
        target: str = "",
        kind: str = "auto",
        window: str = "",
        out: str = "",
        read_image: bool = True,
    ) -> str | ToolResult:
        r"""Capture a running app to PNG, then look at it.

        Use this when the task is about an app rather than a web page: "does my
        iOS app look right in the simulator", "screenshot the Android app",
        "look at the window of the app I am running". For a URL use the page
        camera instead.

        `target` accepts an app name ("Notes"), a window title or number, an
        iOS Simulator name or UDID, or an Android serial. Leave it empty when
        exactly one mobile target is running and that one is used. Call
        `list_capture_targets` when unsure what is available.

        The shot is attached to your context when your model can see images,
        so one call is enough. When your model is text-only but an image model
        is configured, that model reads the shot and its description is
        returned instead. Pass read_image=False to only get the file path.

        Args:
            target (str): App name, window title, window number, simulator
                name/UDID, or Android serial. Empty picks the only running
                mobile target.
            kind (str): "auto" (default), "window" (macOS app window),
                "simulator" (iOS Simulator), "android" (device or emulator),
                or "desktop" (whole screen, macOS only).
            window (str): Window title fragment, when one app owns several
                windows and you want a specific one.
            out (str): Output file or directory; relative paths resolve
                against the workspace. Defaults to the app's shot cache.
            read_image (bool): Attach the screenshot image to your context
                when your model accepts image input. Default True.

        Returns:
            The saved path with its pixel size and the backend that produced
            it, plus the image when the model supports vision.
        """
        backends = self.available_backends()
        if not backends:
            return (
                "Error: no app capture backend is available on this host. "
                "macOS window capture needs /usr/sbin/screencapture, iOS needs "
                "xcrun, Android needs adb. For a web page use the page camera "
                "(capture_page) instead."
            )

        picked = await self._resolve(target, kind, window)
        if isinstance(picked, str):
            return picked

        path = self._output_path(out, picked["slug"])
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass

        error = await self._capture(picked, path)
        if error:
            return f"Error: app capture failed for {picked['label']}: {error}"

        if not path.is_file() or path.stat().st_size == 0:
            if picked["kind"] == "window":
                return f"Error: app capture wrote no pixels for {picked['label']}. {_TCC_HELP}"
            return f"Error: app capture wrote no pixels for {picked['label']}."

        size = image_size(path)
        dims = f"{size[0]}x{size[1]}" if size else "unknown size"
        shot = {
            "path": str(path),
            "label": picked["label"],
            "backend": picked["kind"],
        }

        lines = [
            f"Captured {picked['label']} via {picked['backend']}: "
            f"{path} ({dims})"
        ]

        images: list[str] = []
        read_note: tuple[str, str] | None = None
        if read_image:
            if agent_sees_images(self._agent, self.model_type, self.model_platform):
                images = load_images([shot])
            else:
                note = await describe_images(
                    self._agent, [shot], prompt=self._prompt_for(picked)
                )
                read_note = note
                # A shot with no vision description is worse than useless to a
                # text-only model, so fall back to asking the user to look.
                if note is None:
                    read_note = None

        if images:
            lines.append("Images attached to context: 1.")
        elif not read_image:
            lines.append(
                "No images attached (read_image=False). Open the path with "
                "read_image to view it."
            )
        elif read_note and read_note[1]:
            vision_model, description = read_note
            model = self.model_type or "the active model"
            lines.append(
                f"No images attached: {model} is not known to accept image "
                f"input, so {vision_model} read it:"
            )
            lines.append(description)
        elif read_note:
            vision_model, _ = read_note
            lines.append(
                f"No images attached: {vision_model} returned nothing for this "
                "shot. Open the path with read_image to view it."
            )
        else:
            model = self.model_type or "the active model"
            lines.append(
                f"No images attached: {model} is not known to accept image "
                "input and no image model is configured. Open the path with "
                "read_image to view it."
            )

        text = "\n".join(lines)
        return ToolResult(text=text, images=images) if images else text

    # ------------------------------------------------------------- resolution

    async def _resolve(
        self, target: str, kind: str, window: str
    ) -> dict | str:
        """Pick one capture target, or return the message explaining why not."""
        raw = (target or "").strip()
        wanted = (kind or "auto").strip().lower()
        needle = raw.lower()
        show = f" {window.strip()!r}" if window.strip() else ""

        if wanted in ("desktop", "screen", "display") or needle in (
            "desktop",
            "screen",
            "display",
        ):
            if platform.system() != "Darwin" or not _screencapture_binary():
                return (
                    "Error: whole-screen capture is only available on macOS. "
                    "On this host capture an Android device or emulator "
                    "instead: call list_capture_targets."
                )
            return {
                "kind": "desktop",
                "backend": "whole screen",
                "label": "the whole screen" + show,
                "slug": "desktop",
            }

        want_sim = wanted in ("simulator", "ios", "iphone", "ipad")
        want_android = wanted in ("android", "emulator", "device", "adb")
        want_window = wanted in ("window", "app", "mac", "macos")

        if want_sim:
            resolved = await self._pick_simulator(needle)
            return resolved or self._no_target("iOS Simulator", raw)
        if want_android:
            resolved = await self._pick_android(needle)
            return resolved or self._no_target("Android device", raw)
        if want_window:
            resolved = self._pick_window(needle, window)
            return resolved or self._no_window(raw, window)

        # --- auto: prefer an exact runtime match, then a name match.
        devices = await list_android_devices()
        if raw and any(
            needle == d["serial"].lower() or needle in d["serial"].lower()
            for d in devices
        ):
            resolved = await self._pick_android(needle)
            if resolved:
                return resolved

        simulators = await list_simulators()
        if raw and any(
            needle == s["udid"].lower()
            or needle in s["name"].lower()
            or needle in s["udid"].lower()
            for s in simulators
        ):
            resolved = await self._pick_simulator(needle)
            if resolved:
                return resolved

        if not raw:
            if len(simulators) == 1:
                return await self._pick_simulator("")
            if len(devices) == 1:
                return await self._pick_android("")
            listing = await self._targets_text()
            return (
                "Error: capture_app needs a target. Exactly one target was "
                f"expected but none was picked. Available:\n{listing}"
            )

        resolved = self._pick_window(needle, window)
        if resolved:
            return resolved

        if want_window or platform.system() == "Darwin":
            return self._no_window(raw, window)
        return self._no_target("app", raw)

    async def _pick_simulator(self, needle: str) -> dict | None:
        simulators = await list_simulators()
        if not simulators:
            return None
        match = None
        if needle:
            for sim in simulators:
                if needle in (sim["name"].lower(), sim["udid"].lower()):
                    match = sim
                    break
            if match is None:
                for sim in simulators:
                    if needle in sim["name"].lower() or needle in sim["udid"].lower():
                        match = sim
                        break
        elif len(simulators) == 1:
            match = simulators[0]
        if match is None:
            return None
        return {
            "kind": "simulator",
            "backend": f"iOS Simulator ({match['runtime']})",
            "label": f"iOS Simulator {match['name']}",
            "slug": _safe_name(f"sim-{match['name']}"),
            "udid": match["udid"],
        }

    async def _pick_android(self, needle: str) -> dict | None:
        devices = await list_android_devices()
        if not devices:
            return None
        match = None
        if needle:
            for device in devices:
                if needle == device["serial"].lower():
                    match = device
                    break
            if match is None:
                for device in devices:
                    if needle in device["serial"].lower() or needle in device[
                        "model"
                    ].lower():
                        match = device
                        break
        elif len(devices) == 1:
            match = devices[0]
        if match is None:
            return None
        kind = "emulator" if match["emulator"] else "device"
        label = match["model"] or match["serial"]
        return {
            "kind": "android",
            "backend": f"Android {kind}",
            "label": f"Android {kind} {label}",
            "slug": _safe_name(f"android-{match['serial']}"),
            "serial": match["serial"],
        }

    def _pick_window(self, needle: str, window_hint: str) -> dict | None:
        if platform.system() != "Darwin":
            return None
        windows = list_windows()
        if not windows:
            return None

        hint = (window_hint or "").strip().lower()

        def area(entry: dict) -> float:
            bounds = entry["bounds"]
            return float(bounds[2] * bounds[3]) if bounds else 0.0

        candidates = windows
        if hint:
            narrowed = [w for w in windows if hint in w["title"].lower()]
            candidates = narrowed or windows

        match = None
        if needle.startswith("pid:"):
            try:
                pid = int(needle.split(":", 1)[1])
            except ValueError:
                pid = -1
            match = next((w for w in candidates if w["pid"] == pid), None)
        elif needle.isdigit():
            number = int(needle)
            match = next((w for w in candidates if w["number"] == number), None)
        elif needle:
            exact = [
                w
                for w in candidates
                if needle == w["owner"].lower() or needle == w["title"].lower()
            ]
            fuzzy = [
                w
                for w in candidates
                if needle in w["owner"].lower() or needle in w["title"].lower()
            ]
            pool = exact or fuzzy
            if pool:
                match = max(pool, key=area)
        elif len(candidates) == 1:
            match = candidates[0]

        if match is None or match["number"] is None:
            return None
        label = match["owner"] or f"window {match['number']}"
        if match["title"]:
            label = f'{label} "{match["title"]}"'
        return {
            "kind": "window",
            "backend": "macOS window",
            "label": label,
            "slug": _safe_name(f"win-{match['owner']}-{match['number']}"),
            "number": match["number"],
        }

    def _no_window(self, target: str, window_hint: str) -> str:
        suffix = f" matching {window_hint!r}" if window_hint.strip() else ""
        if platform.system() != "Darwin":
            return (
                "Error: macOS window capture is only available on macOS. "
                "Capturing an iOS Simulator or an Android device works on this "
                "host: call list_capture_targets."
            )
        missing = (
            f"Error: no visible window matches {target!r}{suffix}. The app may "
            "not be running, or it may be minimised. Call list_capture_targets "
            "to see the windows that exist."
        )
        if screen_capture_allowed() is False:
            # Without the grant macOS hides every window title, so a title
            # match can never succeed. Say both facts instead of blaming TCC.
            return (
                missing
                + " Note: macOS also hides window titles without Screen "
                "Recording, so match on the app name. "
                + _TCC_HELP
            )
        return missing

    def _no_target(self, what: str, target: str) -> str:
        where = f" matching {target!r}" if target else ""
        return (
            f"Error: no {what}{where} is running. Call list_capture_targets to "
            "see what is available."
        )

    # -------------------------------------------------------------- capturing

    async def _capture(self, picked: dict, path: Path) -> str | None:
        kind = picked["kind"]

        if kind == "window":
            binary = _screencapture_binary()
            if not binary:
                return "screencapture not found on this host"
            code, _out, err = await _run(
                [
                    binary,
                    "-x",
                    "-o",
                    "-l",
                    str(picked["number"]),
                    "-t",
                    "png",
                    str(path),
                ],
                timeout=_SAFE_CAPTURE_SECONDS,
            )
            if code == 0:
                return None
            detail = err.decode("utf-8", "replace").strip()
            if "could not create image" in detail.lower() or not detail:
                return _TCC_HELP
            return detail[:300]

        if kind == "simulator":
            code, _out, err = await _run(
                [
                    "xcrun",
                    "simctl",
                    "io",
                    picked["udid"],
                    "screenshot",
                    "--type=png",
                    str(path),
                ],
                timeout=_SAFE_CAPTURE_SECONDS,
            )
            if code == 0:
                return None
            return err.decode("utf-8", "replace").strip()[:300] or "simctl failed"

        if kind == "android":
            adb = _adb_binary()
            if not adb:
                return "adb not found"
            code, out, err = await _run(
                [adb, "-s", picked["serial"], "exec-out", "screencap", "-p"],
                timeout=_SAFE_CAPTURE_SECONDS,
            )
            if code == 0 and out.startswith(b"\x89PNG"):
                path.write_bytes(out)
                return None
            detail = err.decode("utf-8", "replace").strip()
            return detail[:300] or "screencap returned no PNG data"

        if kind == "desktop":
            binary = _screencapture_binary()
            if not binary:
                return "whole-screen capture is only available on macOS"
            code, _out, err = await _run(
                [binary, "-x", "-t", "png", str(path)],
                timeout=_SAFE_CAPTURE_SECONDS,
            )
            if code == 0:
                return None
            detail = err.decode("utf-8", "replace").strip()
            if not detail or "could not create image" in detail.lower():
                return _TCC_HELP
            return detail[:300]

        return f"unknown capture kind {kind!r}"

    # --------------------------------------------------------------- internals

    def _output_path(self, out: str, slug: str) -> Path:
        if out:
            path = Path(out).expanduser()
            if not path.is_absolute():
                path = Path(self.working_directory) / path
            if path.suffix.lower() in _IMAGE_SUFFIXES:
                return path
            return path / f"{slug}.png"

        if self.shot_dir:
            root = Path(self.shot_dir).expanduser()
        else:
            root = (
                Path.home()
                / ".undisclosed"
                / "screenshots"
                / _safe_name(str(self.api_task_id or "default"))
            )
        return root / f"{slug}.png"

    def _prompt_for(self, picked: dict) -> str:
        if picked["kind"] in ("simulator", "android"):
            return (
                "This is a screenshot of a running mobile app. Describe what "
                "the screen shows so a model that cannot see images can reason "
                "about it. Cover: which screen or view is visible, the visible "
                "titles and key text, the layout with any obvious spacing or "
                "alignment problems, colors, and any visible defect such as "
                "clipped text, overlapping content, or a missing image. Be "
                "specific and factual."
            )
        if picked["kind"] == "window":
            return (
                "This is a screenshot of a running desktop application window. "
                "Describe what it shows so a model that cannot see images can "
                "reason about it: which app, the visible headings and key text, "
                "layout, colors, and any obvious visual defect. Be specific "
                "and factual."
            )
        return READ_PROMPT
