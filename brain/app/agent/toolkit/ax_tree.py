# Copyright (c) 2026 Simon Ugorji
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Accessibility (AXUIElement) bridge for element-level desktop control.

A screenshot gives pixels; this gives the UI itself: roles, labels, frames and
the actions each element supports. Acting on an element survives a window that
moves or a layout that reflows, where a stored coordinate does not.

Everything here is synchronous and macOS-only, because every call blocks on the
target app replying. The toolkit runs it in a thread.
"""

import ctypes
import ctypes.util
import logging
import platform
import time

logger = logging.getLogger("ax_tree")

_CF_UTF8 = 0x08000100
_CF_NUMBER_DOUBLE = 13

# AXValueType
_VALUE_CGPOINT = 1
_VALUE_CGSIZE = 2
_VALUE_CGRECT = 3

ERR_SUCCESS = 0
ERR_ILLEGAL_ARGUMENT = -25201
ERR_INVALID_ELEMENT = -25202
ERR_CANNOT_COMPLETE = -25204
ERR_UNSUPPORTED_ATTRIBUTE = -25205
ERR_UNSUPPORTED_ACTION = -25206
ERR_NOT_IMPLEMENTED = -25208
ERR_API_DISABLED = -25211
ERR_NO_VALUE = -25212

# Roles that carry no information of their own. Their children are hoisted so
# the tree stays readable and the node budget goes to things you can act on.
_OPAQUE_ROLES = frozenset({"AXUnknown", "AXGroup", "AXLayoutItem"})

_MESSAGING_TIMEOUT = 1.5
_WALL_CLOCK_BUDGET = 8.0


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


_LIBS = None


def _libs():
    """(ApplicationServices, CoreFoundation) with the signatures we need."""
    global _LIBS
    if _LIBS is not None:
        return _LIBS
    if platform.system() != "Darwin":
        _LIBS = False
        return _LIBS

    try:
        ax = ctypes.CDLL(
            ctypes.util.find_library("ApplicationServices")
            or "/System/Library/Frameworks/ApplicationServices.framework/"
            "ApplicationServices"
        )
        cf = ctypes.CDLL(
            ctypes.util.find_library("CoreFoundation")
            or "/System/Library/Frameworks/CoreFoundation.framework/"
            "CoreFoundation"
        )

        cf.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_uint32,
        ]
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringGetCString.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_long,
            ctypes.c_uint32,
        ]
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFStringGetLength.argtypes = [ctypes.c_void_p]
        cf.CFStringGetLength.restype = ctypes.c_long
        cf.CFGetTypeID.argtypes = [ctypes.c_void_p]
        cf.CFGetTypeID.restype = ctypes.c_ulong
        cf.CFStringGetTypeID.restype = ctypes.c_ulong
        cf.CFBooleanGetTypeID.restype = ctypes.c_ulong
        cf.CFNumberGetTypeID.restype = ctypes.c_ulong
        cf.CFArrayGetTypeID.restype = ctypes.c_ulong
        cf.CFBooleanGetValue.argtypes = [ctypes.c_void_p]
        cf.CFBooleanGetValue.restype = ctypes.c_bool
        cf.CFNumberGetValue.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        cf.CFNumberGetValue.restype = ctypes.c_bool
        cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
        cf.CFArrayGetCount.restype = ctypes.c_long
        cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
        cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
        cf.CFRetain.argtypes = [ctypes.c_void_p]
        cf.CFRetain.restype = ctypes.c_void_p
        cf.CFRelease.argtypes = [ctypes.c_void_p]

        ax.AXUIElementCreateSystemWide.restype = ctypes.c_void_p
        ax.AXUIElementCreateApplication.argtypes = [ctypes.c_int32]
        ax.AXUIElementCreateApplication.restype = ctypes.c_void_p
        ax.AXUIElementCopyAttributeValue.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        ax.AXUIElementCopyAttributeValue.restype = ctypes.c_int32
        ax.AXUIElementCopyActionNames.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        ax.AXUIElementCopyActionNames.restype = ctypes.c_int32
        ax.AXUIElementPerformAction.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        ax.AXUIElementPerformAction.restype = ctypes.c_int32
        ax.AXUIElementSetAttributeValue.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        ax.AXUIElementSetAttributeValue.restype = ctypes.c_int32
        ax.AXUIElementGetPid.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int32),
        ]
        ax.AXUIElementGetPid.restype = ctypes.c_int32
        ax.AXUIElementCopyElementAtPosition.argtypes = [
            ctypes.c_void_p,
            ctypes.c_float,
            ctypes.c_float,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        ax.AXUIElementCopyElementAtPosition.restype = ctypes.c_int32
        ax.AXUIElementSetMessagingTimeout.argtypes = [
            ctypes.c_void_p,
            ctypes.c_float,
        ]
        ax.AXUIElementSetMessagingTimeout.restype = ctypes.c_int32
        ax.AXValueGetValue.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        ax.AXValueGetValue.restype = ctypes.c_bool
        ax.AXValueGetType.argtypes = [ctypes.c_void_p]
        ax.AXValueGetType.restype = ctypes.c_uint32
        ax.AXValueGetTypeID.restype = ctypes.c_ulong
        ax.AXIsProcessTrusted.restype = ctypes.c_bool

        _LIBS = (ax, cf)
    except Exception:
        logger.debug("AXUIElement bridge unavailable", exc_info=True)
        _LIBS = False
    return _LIBS


def available() -> bool:
    return bool(_libs())


def trusted() -> bool | None:
    libs = _libs()
    if not libs:
        return None
    try:
        return bool(libs[0].AXIsProcessTrusted())
    except Exception:
        return None


def resolve_target(
    app: str, windows: list[dict]
) -> tuple[int | None, str, str]:
    """Map an app name (or pid, or "frontmost") to a pid.

    `windows` is the on-screen window list, front to back, which already
    carries owner names and pids and costs no extra permission. Returns
    (pid, owner name, error).
    """
    entries = [entry for entry in windows if entry.get("pid")]
    name = (app or "").strip()

    if not name:
        if not entries:
            return None, "", (
                "No app windows are on screen, so there is no frontmost app. "
                "Open the app first, or pass its name."
            )
        front = entries[0]
        return int(front["pid"]), front.get("owner") or "", ""

    if name.isdigit():
        pid = int(name)
        owner = next(
            (entry.get("owner") for entry in entries if int(entry["pid"]) == pid),
            "",
        )
        return pid, owner or f"pid {pid}", ""

    lowered = name.lower()
    exact = [
        entry for entry in entries if (entry.get("owner") or "").lower() == lowered
    ]
    matches = exact or [
        entry for entry in entries if lowered in (entry.get("owner") or "").lower()
    ]
    if not matches:
        owners = sorted(
            {entry["owner"] for entry in entries if entry.get("owner")}
        )
        return None, "", (
            f"No on-screen app matches {app!r}. Visible apps: "
            f"{', '.join(owners) or 'none'}."
        )
    chosen = matches[0]
    return int(chosen["pid"]), chosen.get("owner") or app, ""


def error_text(code: int) -> str:
    if code == ERR_SUCCESS:
        return "ok"
    return {
        ERR_ILLEGAL_ARGUMENT: "AX rejected the argument",
        ERR_INVALID_ELEMENT: "the element no longer exists",
        ERR_CANNOT_COMPLETE: "the app did not answer (busy or modal)",
        ERR_UNSUPPORTED_ATTRIBUTE: "the element has no such attribute",
        ERR_UNSUPPORTED_ACTION: "the element does not support that action",
        ERR_NOT_IMPLEMENTED: "the app does not implement that action",
        ERR_API_DISABLED: "Accessibility access is disabled for this process",
        ERR_NO_VALUE: "the element has no value",
    }.get(code, f"AX error {code}")


# ------------------------------------------------------------------- CF values


def _release(cf, ref) -> None:
    if ref:
        try:
            cf.CFRelease(ref)
        except Exception:
            pass


def _cf_string(text: str):
    libs = _libs()
    if not libs:
        return None
    _, cf = libs
    try:
        return cf.CFStringCreateWithCString(
            None, text.encode("utf-8"), _CF_UTF8
        )
    except Exception:
        return None


def _to_text(ref) -> str | None:
    """Render a CF value as text. None when it is not something worth showing."""
    libs = _libs()
    if not libs or not ref:
        return None
    ax, cf = libs
    try:
        type_id = cf.CFGetTypeID(ref)
        if type_id == cf.CFStringGetTypeID():
            length = cf.CFStringGetLength(ref)
            if length <= 0:
                return ""
            buffer = ctypes.create_string_buffer(length * 4 + 8)
            if cf.CFStringGetCString(ref, buffer, len(buffer), _CF_UTF8):
                return buffer.value.decode("utf-8", "replace")
            return None
        if type_id == cf.CFBooleanGetTypeID():
            return "true" if cf.CFBooleanGetValue(ref) else "false"
        if type_id == cf.CFNumberGetTypeID():
            number = ctypes.c_double(0)
            if cf.CFNumberGetValue(
                ref, _CF_NUMBER_DOUBLE, ctypes.byref(number)
            ):
                value = number.value
                return str(int(value)) if value == int(value) else f"{value:g}"
            return None
        if type_id == ax.AXValueGetTypeID():
            kind = ax.AXValueGetType(ref)
            if kind == _VALUE_CGPOINT:
                point = _CGPoint()
                if ax.AXValueGetValue(ref, kind, ctypes.byref(point)):
                    return f"{point.x:g},{point.y:g}"
            elif kind == _VALUE_CGSIZE:
                size = _CGSize()
                if ax.AXValueGetValue(ref, kind, ctypes.byref(size)):
                    return f"{size.width:g}x{size.height:g}"
            elif kind == _VALUE_CGRECT:
                rect = _CGRect()
                if ax.AXValueGetValue(ref, kind, ctypes.byref(rect)):
                    return (
                        f"{rect.origin.x:g},{rect.origin.y:g} "
                        f"{rect.size.width:g}x{rect.size.height:g}"
                    )
    except Exception:
        logger.debug("could not read CF value", exc_info=True)
    return None


def _attr(ref, name: str):
    """A copied attribute (caller releases), or None."""
    libs = _libs()
    if not libs or not ref:
        return None
    ax, cf = libs
    key = _cf_string(name)
    if not key:
        return None
    out = ctypes.c_void_p()
    try:
        code = ax.AXUIElementCopyAttributeValue(ref, key, ctypes.byref(out))
    finally:
        _release(cf, key)
    return out.value if code == ERR_SUCCESS and out.value else None


def _text_attr(ref, name: str) -> str:
    libs = _libs()
    if not libs:
        return ""
    _, cf = libs
    value = _attr(ref, name)
    if not value:
        return ""
    try:
        return _to_text(value) or ""
    finally:
        _release(cf, value)


def _frame(ref) -> tuple[int, int, int, int] | None:
    libs = _libs()
    if not libs:
        return None
    ax, cf = libs
    position = _attr(ref, "AXPosition")
    if not position:
        return None
    size = _attr(ref, "AXSize")
    try:
        point = _CGPoint()
        if not ax.AXValueGetValue(position, _VALUE_CGPOINT, ctypes.byref(point)):
            return None
        width = height = 0.0
        if size:
            dimensions = _CGSize()
            if ax.AXValueGetValue(
                size, _VALUE_CGSIZE, ctypes.byref(dimensions)
            ):
                width, height = dimensions.width, dimensions.height
        return (int(point.x), int(point.y), int(width), int(height))
    finally:
        _release(cf, position)
        _release(cf, size)


def _actions(ref) -> list[str]:
    libs = _libs()
    if not libs:
        return []
    ax, cf = libs
    out = ctypes.c_void_p()
    try:
        if ax.AXUIElementCopyActionNames(ref, ctypes.byref(out)) != ERR_SUCCESS:
            return []
        if not out.value:
            return []
        names = []
        for index in range(cf.CFArrayGetCount(out.value)):
            names.append(
                _to_text(cf.CFArrayGetValueAtIndex(out.value, index)) or ""
            )
        return [name for name in names if name]
    except Exception:
        return []
    finally:
        _release(cf, out.value)


def _children(ref):
    """Child elements, each retained so they outlive the array we release."""
    libs = _libs()
    if not libs:
        return []
    ax, cf = libs
    array = _attr(ref, "AXChildren")
    if not array:
        return []
    children = []
    try:
        for index in range(cf.CFArrayGetCount(array)):
            child = cf.CFArrayGetValueAtIndex(array, index)
            if child:
                cf.CFRetain(child)
                children.append(child)
    finally:
        _release(cf, array)
    return children


# --------------------------------------------------------------------- reading


def _describe(ref, depth: int, want_actions: bool = True) -> dict | None:
    role = _text_attr(ref, "AXRole")
    if not role:
        return None
    subrole = _text_attr(ref, "AXSubrole")
    title = _text_attr(ref, "AXTitle")
    value = _text_attr(ref, "AXValue")
    description = _text_attr(ref, "AXDescription")
    identifier = _text_attr(ref, "AXIdentifier")
    return {
        "ref": ref,
        "depth": depth,
        "role": role,
        "subrole": subrole,
        "title": title,
        "value": value,
        "description": description,
        "identifier": identifier,
        "frame": _frame(ref),
        "actions": _actions(ref) if want_actions else [],
    }


def _label(node: dict) -> str:
    return (
        node["title"]
        or node["description"]
        or node["identifier"]
        or node["value"]
    )


def _matches(node: dict, needle: str) -> bool:
    if not needle:
        return True
    haystack = " ".join(
        [
            node["role"],
            node["subrole"],
            node["title"],
            node["value"],
            node["description"],
            node["identifier"],
        ]
    ).lower()
    return needle in haystack


def snapshot(
    pid: int,
    *,
    max_depth: int = 8,
    max_nodes: int = 150,
    query: str = "",
    want_actions: bool = True,
) -> tuple[list[dict], str]:
    """Walk an app's accessibility tree.

    Returns (rows, error). Each row is a dict with a retained `ref`, so the
    caller must pass the list to `release_nodes` when it is done with it.
    """
    libs = _libs()
    if not libs:
        return [], "Accessibility trees are only available on macOS."
    ax, cf = libs

    root = ax.AXUIElementCreateApplication(int(pid))
    if not root:
        return [], f"Could not open pid {pid} as an accessibility app."

    needle = (query or "").strip().lower()
    rows: list[dict] = []
    handed: set[int] = set()
    retained: list[int] = []
    seen: set[int] = set()
    deadline = time.monotonic() + _WALL_CLOCK_BUDGET

    try:
        ax.AXUIElementSetMessagingTimeout(root, _MESSAGING_TIMEOUT)
        stack: list[tuple[int, int]] = [(root, 0)]
        visited = 0
        while stack and len(rows) < max_nodes and time.monotonic() < deadline:
            ref, depth = stack.pop()
            if not ref or ref in seen:
                continue
            seen.add(ref)
            visited += 1
            if visited > max_nodes * 12:
                break

            node = _describe(ref, depth, want_actions)
            if node is None:
                continue
            children = _children(ref)
            retained.extend(children)

            emit = bool(_label(node) or node["frame"] or node["actions"])
            opaque = node["role"] in _OPAQUE_ROLES
            if emit and _matches(node, needle):
                rows.append(node)
                handed.add(ref)
            elif emit and needle:
                # Filtered out, but keep it as a container to walk through.
                opaque = False

            child_depth = depth if opaque and not emit else depth + 1
            if child_depth <= max_depth:
                for child in reversed(children):
                    stack.append((child, child_depth))
    except Exception:
        logger.debug("accessibility walk failed", exc_info=True)
    finally:
        for child in retained:
            if child not in handed:
                _release(cf, child)
        #the app root's +1 moves into the returned rows when it is emitted, so
        #releasing it here as well left a dangling ref that release_nodes freed
        if root not in handed:
            _release(cf, root)

    if not rows:
        return [], (
            "No accessible elements came back for that app. Either the "
            "Accessibility grant is missing, or the app exposes no "
            "accessibility tree."
        )
    return rows, ""


def release_nodes(rows: list[dict]) -> None:
    libs = _libs()
    if not libs:
        return
    _, cf = libs
    for row in rows:
        _release(cf, row.get("ref"))
        row["ref"] = None


def element_at(x: int, y: int) -> tuple[dict | None, str]:
    """The element under a screen point, plus the pid that owns it."""
    libs = _libs()
    if not libs:
        return None, "Accessibility hit-testing is only available on macOS."
    ax, cf = libs

    system = ax.AXUIElementCreateSystemWide()
    if not system:
        return None, "Could not open the system-wide accessibility element."
    found = ctypes.c_void_p()
    try:
        ax.AXUIElementSetMessagingTimeout(system, _MESSAGING_TIMEOUT)
        code = ax.AXUIElementCopyElementAtPosition(
            system, ctypes.c_float(float(x)), ctypes.c_float(float(y)),
            ctypes.byref(found),
        )
        if code != ERR_SUCCESS or not found.value:
            return None, f"No element at {int(x)}, {int(y)}: {error_text(code)}"
        node = _describe(found.value, 0)
        if node is None:
            _release(cf, found.value)
            return None, f"An element exists at {int(x)}, {int(y)} but has no role."
        pid = ctypes.c_int32(0)
        if ax.AXUIElementGetPid(found.value, ctypes.byref(pid)) == ERR_SUCCESS:
            node["pid"] = int(pid.value)
        else:
            node["pid"] = None
        return node, ""
    finally:
        _release(cf, system)


# --------------------------------------------------------------------- acting


def perform(ref, action: str) -> int:
    libs = _libs()
    if not libs:
        return ERR_ILLEGAL_ARGUMENT
    ax, cf = libs
    key = _cf_string(action)
    if not key:
        return ERR_ILLEGAL_ARGUMENT
    try:
        return ax.AXUIElementPerformAction(ref, key)
    finally:
        _release(cf, key)


def set_value(ref, text: str) -> int:
    libs = _libs()
    if not libs:
        return ERR_ILLEGAL_ARGUMENT
    ax, cf = libs
    key = _cf_string("AXValue")
    value = _cf_string(text)
    if not key or not value:
        _release(cf, key)
        _release(cf, value)
        return ERR_ILLEGAL_ARGUMENT
    try:
        return ax.AXUIElementSetAttributeValue(ref, key, value)
    finally:
        _release(cf, key)
        _release(cf, value)


# ------------------------------------------------------------------ formatting


def _short(text: str, limit: int = 60) -> str:
    collapsed = " ".join(str(text).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "\u2026"


def format_row(row: dict, element_id: str = "") -> str:
    """One line per element: id, role, label, value, frame, actions."""
    parts = [element_id] if element_id else []
    role = row.get("role") or "AXUnknown"
    if row.get("subrole"):
        role = f"{role}[{row['subrole']}]"
    parts.append(role)
    label = row.get("title") or row.get("description")
    if label:
        parts.append(f'"{_short(label)}"')
    if row.get("value") and row["value"] != label:
        parts.append(f'value="{_short(row["value"])}"')
    if row.get("identifier"):
        parts.append(f"id={_short(row['identifier'], 30)}")
    frame = row.get("frame")
    if frame:
        parts.append(f"@ {frame[0]},{frame[1]} {frame[2]}x{frame[3]}")
    actions = [name for name in row.get("actions") or [] if name != "AXPress"]
    if row.get("actions"):
        if "AXPress" in row["actions"]:
            actions.insert(0, "AXPress")
        parts.append("actions=" + ",".join(actions[:5]))
    return " ".join(parts)


def format_tree(rows: list[dict], prefix: str = "e") -> list[str]:
    lines = []
    for index, row in enumerate(rows, start=1):
        indent = "  " * min(row.get("depth", 0), 8)
        lines.append(f"{indent}{format_row(row, f'{prefix}{index}')}")
    return lines


def center(frame) -> tuple[int, int] | None:
    if not frame:
        return None
    x, y, width, height = frame
    if width <= 0 or height <= 0:
        return None
    return x + width // 2, y + height // 2
