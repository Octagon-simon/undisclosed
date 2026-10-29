# Copyright (c) 2026 Simon Ugorji
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

import pytest

from app.agent.toolkit import ax_tree, desktop_toolkit as mod
from app.agent.toolkit.desktop_toolkit import DesktopToolkit

pytestmark = pytest.mark.unit


def _raw(fn):
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


WINDOWS = [
    {"owner": "Notes", "pid": 501, "number": 1, "title": "Notes", "bounds": None},
    {"owner": "Brave Browser", "pid": 502, "number": 2, "title": "", "bounds": None},
]


@pytest.fixture
def toolkit(tmp_path):
    return DesktopToolkit(api_task_id="t", working_directory=str(tmp_path))


@pytest.fixture
def ax_ready(monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(mod, "_quartz", lambda: (object(), object()))
    monkeypatch.setattr(mod, "accessibility_trusted", lambda: True)
    monkeypatch.setattr(mod.ax_tree, "available", lambda: True)
    monkeypatch.setattr(mod, "list_windows", lambda: list(WINDOWS))
    monkeypatch.setattr(mod.ax_tree, "release_nodes", lambda rows: None)


def _row(role="AXButton", title="Save", actions=("AXPress",), frame=(10, 20, 60, 30)):
    return {
        "ref": 1234,
        "depth": 0,
        "role": role,
        "subrole": "",
        "title": title,
        "value": "",
        "description": "",
        "identifier": "",
        "frame": frame,
        "actions": list(actions),
    }


def test_resolve_target_prefers_frontmost_when_unnamed():
    pid, owner, error = ax_tree.resolve_target("", WINDOWS)
    assert (pid, owner, error) == (501, "Notes", "")


def test_resolve_target_matches_app_name_case_insensitively():
    pid, owner, _ = ax_tree.resolve_target("brave browser", WINDOWS)
    assert (pid, owner) == (502, "Brave Browser")


def test_resolve_target_accepts_pid():
    pid, owner, _ = ax_tree.resolve_target("502", WINDOWS)
    assert (pid, owner) == (502, "Brave Browser")


def test_resolve_target_lists_visible_apps_when_missing():
    pid, _, error = ax_tree.resolve_target("Figma", WINDOWS)
    assert pid is None
    assert "Brave Browser" in error and "Notes" in error


def test_format_row_carries_id_role_label_and_frame():
    line = ax_tree.format_row(_row(), "s3e7")
    assert line.startswith("s3e7 AXButton")
    assert '"Save"' in line
    assert "@ 10,20 60x30" in line
    assert "actions=AXPress" in line


def test_format_row_shortens_long_labels():
    line = ax_tree.format_row(_row(title="x" * 200))
    assert "x" * 200 not in line
    assert "\u2026" in line


def test_center_of_a_frame():
    assert ax_tree.center((100, 200, 40, 20)) == (120, 210)
    assert ax_tree.center((100, 200, 0, 0)) is None
    assert ax_tree.center(None) is None


def test_error_text_names_the_common_failures():
    assert "no longer exists" in ax_tree.error_text(ax_tree.ERR_INVALID_ELEMENT)
    assert "Accessibility" in ax_tree.error_text(ax_tree.ERR_API_DISABLED)


def test_snapshot_without_macos_reports_why(monkeypatch):
    monkeypatch.setattr(ax_tree, "_libs", lambda: False)
    rows, error = ax_tree.snapshot(1)
    assert rows == []
    assert "macOS" in error


@pytest.mark.asyncio
async def test_ui_tree_refuses_without_accessibility(monkeypatch, toolkit):
    monkeypatch.setattr(mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(mod, "_quartz", lambda: (object(), object()))
    monkeypatch.setattr(mod, "accessibility_trusted", lambda: False)

    result = await _raw(toolkit.ui_tree)(toolkit, "Notes")
    assert "Accessibility" in result


@pytest.mark.asyncio
async def test_ui_tree_labels_elements_with_snapshot_ids(monkeypatch, ax_ready, toolkit):
    monkeypatch.setattr(
        mod.ax_tree, "snapshot", lambda pid, **kwargs: ([_row()], "")
    )

    result = await _raw(toolkit.ui_tree)(toolkit, "Notes")
    assert "Notes (pid 501)" in result
    assert "s1e1 AXButton" in result
    assert 'click_element("s1e1")' in result


@pytest.mark.asyncio
async def test_ui_tree_explains_an_empty_tree(monkeypatch, ax_ready, toolkit):
    monkeypatch.setattr(
        mod.ax_tree, "snapshot", lambda pid, **kwargs: ([], "nothing here")
    )

    result = await _raw(toolkit.ui_tree)(toolkit, "Notes")
    assert "nothing here" in result
    assert toolkit._ax_index == {}


@pytest.mark.asyncio
async def test_click_element_presses_via_accessibility(monkeypatch, ax_ready, toolkit):
    monkeypatch.setattr(
        mod.ax_tree, "snapshot", lambda pid, **kwargs: ([_row()], "")
    )
    performed = []
    monkeypatch.setattr(
        mod.ax_tree,
        "perform",
        lambda ref, action: performed.append((ref, action)) or 0,
    )
    await _raw(toolkit.ui_tree)(toolkit, "Notes")

    result = await _raw(toolkit.click_element)(toolkit, "s1e1")
    assert performed == [(1234, "AXPress")]
    assert "AXPress" in result


@pytest.mark.asyncio
async def test_click_element_falls_back_to_the_frame_centre(monkeypatch, ax_ready, toolkit):
    monkeypatch.setattr(
        mod.ax_tree,
        "snapshot",
        lambda pid, **kwargs: ([_row(role="AXStaticText", actions=())], ""),
    )
    clicks = []
    monkeypatch.setattr(
        mod, "_click", lambda x, y, button, count: clicks.append((x, y))
    )
    await _raw(toolkit.ui_tree)(toolkit, "Notes")

    result = await _raw(toolkit.click_element)(toolkit, "s1e1")
    assert clicks == [(40, 35)]
    assert "Clicked" in result


@pytest.mark.asyncio
async def test_stale_element_id_asks_for_a_new_tree(monkeypatch, ax_ready, toolkit):
    monkeypatch.setattr(
        mod.ax_tree, "snapshot", lambda pid, **kwargs: ([_row()], "")
    )
    await _raw(toolkit.ui_tree)(toolkit, "Notes")
    await _raw(toolkit.ui_tree)(toolkit, "Notes")

    result = await _raw(toolkit.click_element)(toolkit, "s1e1")
    assert "older snapshot" in result


@pytest.mark.asyncio
async def test_set_element_value_reports_unwritable_fields(monkeypatch, ax_ready, toolkit):
    monkeypatch.setattr(
        mod.ax_tree,
        "snapshot",
        lambda pid, **kwargs: ([_row(role="AXImage", actions=())], ""),
    )
    monkeypatch.setattr(
        mod.ax_tree,
        "set_value",
        lambda ref, text: ax_tree.ERR_UNSUPPORTED_ATTRIBUTE,
    )
    await _raw(toolkit.ui_tree)(toolkit, "Notes")

    result = await _raw(toolkit.set_element_value)(toolkit, "s1e1", "hello")
    assert "Could not write into" in result
    assert "type_text" in result


@pytest.mark.asyncio
async def test_element_at_registers_the_hit(monkeypatch, ax_ready, toolkit):
    node = _row(role="AXButton", title="OK", actions=("AXPress",))
    node["pid"] = 501
    monkeypatch.setattr(mod.ax_tree, "element_at", lambda x, y: (node, ""))

    result = await _raw(toolkit.element_at)(toolkit, 12, 34)
    assert "s1e1 AXButton" in result
    assert "in Notes" in result
    assert "s1e1" in toolkit._ax_index


class _FakeCF:
    def __init__(self):
        self.released = []

    def CFRelease(self, ref):
        self.released.append(ref)


class _FakeAX:
    def AXUIElementCreateApplication(self, pid):
        return 900

    def AXUIElementSetMessagingTimeout(self, ref, seconds):
        return 0


def _fake_libs(cf):
    return (_FakeAX(), cf)


def _app_row(ref, depth, want_actions=True):
    return {
        "ref": ref,
        "depth": depth,
        "role": "AXApplication",
        "subrole": "",
        "title": "Notes",
        "value": "",
        "description": "",
        "identifier": "",
        "frame": (0, 0, 100, 100),
        "actions": [],
    }


def test_snapshot_leaves_the_emitted_root_to_release_nodes(monkeypatch):
    cf = _FakeCF()
    monkeypatch.setattr(ax_tree, "_libs", lambda: _fake_libs(cf))
    monkeypatch.setattr(ax_tree, "_describe", _app_row)
    monkeypatch.setattr(ax_tree, "_children", lambda ref: [])

    rows, error = ax_tree.snapshot(501)

    assert error == ""
    assert [row["ref"] for row in rows] == [900]
    #the +1 from AXUIElementCreateApplication belongs to the rows now
    assert cf.released == []

    ax_tree.release_nodes(rows)
    assert cf.released == [900]


def test_snapshot_releases_the_root_when_no_row_kept_it(monkeypatch):
    cf = _FakeCF()
    monkeypatch.setattr(ax_tree, "_libs", lambda: _fake_libs(cf))
    monkeypatch.setattr(ax_tree, "_describe", lambda ref, depth, want_actions=True: None)
    monkeypatch.setattr(ax_tree, "_children", lambda ref: [])

    rows, error = ax_tree.snapshot(501)

    assert rows == []
    assert "No accessible elements" in error
    assert cf.released == [900]

