# Copyright (c) 2026 Simon Ugorji
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

import pytest

from app.agent.toolkit import desktop_toolkit as mod
from app.agent.toolkit.desktop_toolkit import DesktopToolkit

pytestmark = pytest.mark.unit


def _raw(fn):
    """Strip the listen_toolkit wrappers, which require a live task lock."""
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


@pytest.fixture
def toolkit(tmp_path):
    return DesktopToolkit(api_task_id="test-task", working_directory=str(tmp_path))


@pytest.fixture
def trusted(monkeypatch):
    """Pretend we are on a trusted Mac so the guard lets calls through."""
    monkeypatch.setattr(mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(mod, "_quartz", lambda: (object(), object()))
    monkeypatch.setattr(mod, "accessibility_trusted", lambda: True)


def test_available_is_false_off_macos(monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Linux")
    assert DesktopToolkit.available() is False


def test_available_is_false_without_coregraphics(monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(mod, "_quartz", lambda: False)
    assert DesktopToolkit.available() is False


@pytest.mark.asyncio
async def test_status_explains_missing_platform(monkeypatch, toolkit):
    monkeypatch.setattr(mod.platform, "system", lambda: "Linux")
    result = await _raw(toolkit.desktop_status)(toolkit)
    assert "not available on Linux" in result


@pytest.mark.asyncio
async def test_click_refuses_without_accessibility(monkeypatch, toolkit):
    monkeypatch.setattr(mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(mod, "_quartz", lambda: (object(), object()))
    monkeypatch.setattr(mod, "accessibility_trusted", lambda: False)

    posted = []
    monkeypatch.setattr(mod, "_post_mouse", lambda *a, **k: posted.append(a))

    result = await _raw(toolkit.mouse_click)(toolkit, 10, 20)
    assert "Accessibility" in result
    assert posted == []


@pytest.mark.asyncio
async def test_click_moves_then_clicks_at_the_given_point(
    monkeypatch, trusted, toolkit
):
    moved, clicked = [], []
    monkeypatch.setattr(
        mod, "_post_mouse", lambda event, x, y, button="left": moved.append((event, x, y))
    )
    monkeypatch.setattr(
        mod, "_click", lambda x, y, button, clicks: clicked.append((x, y, button, clicks))
    )

    result = await _raw(toolkit.mouse_click)(toolkit, 120, 240, "right", 2)
    assert moved == [(mod._MOUSE_MOVED, 120, 240)]
    assert clicked == [(120, 240, "right", 2)]
    assert "double-click" in result


@pytest.mark.asyncio
async def test_click_requires_both_coordinates(trusted, toolkit):
    result = await _raw(toolkit.mouse_click)(toolkit, 10, None)
    assert "both x and y" in result


@pytest.mark.asyncio
async def test_click_rejects_unknown_button(trusted, toolkit):
    result = await _raw(toolkit.mouse_click)(toolkit, 1, 2, "thumb")
    assert "left" in result and "right" in result


def test_parse_keys_splits_modifiers():
    assert mod.parse_keys("cmd+shift+4") == (["cmd", "shift"], "4")
    assert mod.parse_keys(["ctrl", "S"]) == (["ctrl"], "s")
    with pytest.raises(ValueError):
        mod.parse_keys("")


def test_keycode_lookup():
    assert mod.keycode_for("a") == 0
    assert mod.keycode_for("4") == 21
    assert mod.keycode_for("enter") == 76
    assert mod.keycode_for("not-a-key") is None


def test_current_channel_defaults_to_desktop_without_a_run():
    assert mod.current_channel() == "desktop"


def test_current_channel_reads_the_run_context():
    from types import SimpleNamespace

    from app.run_context import current_run_context

    token = current_run_context.set(SimpleNamespace(channel="Slack"))
    try:
        assert mod.current_channel() == "slack"
    finally:
        current_run_context.reset(token)


@pytest.mark.asyncio
async def test_input_refuses_a_turn_from_another_channel(monkeypatch, trusted, toolkit):
    monkeypatch.setattr(mod, "current_channel", lambda: "slack")
    posted = []
    monkeypatch.setattr(mod, "_post_mouse", lambda *a, **k: posted.append(a))

    result = await _raw(toolkit.mouse_click)(toolkit, 10, 20)
    assert "only runs for turns started on this machine" in result
    assert "slack" in result
    assert posted == []


def test_input_allows_the_embedded_editor_panel(monkeypatch, trusted, toolkit):
    """The panel sends channel 'web'; that is the local editor, not a remote one."""
    monkeypatch.setattr(mod, "current_channel", lambda: "web")
    assert toolkit._blocked() is None


@pytest.mark.asyncio
async def test_press_keys_sends_keycode_with_modifier_flags(
    monkeypatch, trusted, toolkit
):
    events = []
    monkeypatch.setattr(
        mod, "_post_key", lambda code, flags, down: events.append((code, flags, down))
    )

    result = await _raw(toolkit.press_keys)(toolkit, "cmd+shift+4")
    expected_flags = mod._MODIFIERS["cmd"] | mod._MODIFIERS["shift"]
    assert events == [(21, expected_flags, True), (21, expected_flags, False)]
    assert "cmd+shift+4" in result


@pytest.mark.asyncio
async def test_press_keys_rejects_unknown_modifier(monkeypatch, trusted, toolkit):
    monkeypatch.setattr(mod, "_post_key", lambda *a: pytest.fail("posted"))
    result = await _raw(toolkit.press_keys)(toolkit, "hyper+a")
    assert "Unknown modifier" in result


@pytest.mark.asyncio
async def test_type_text_sends_every_character_in_chunks(
    monkeypatch, trusted, toolkit
):
    chunks = []
    monkeypatch.setattr(mod, "_post_text", lambda chunk: chunks.append(chunk) or True)

    text = "abcdefghijklmnopqrstuvwxyz"
    result = await _raw(toolkit.type_text)(toolkit, text)
    assert "".join(chunks) == text
    assert f"{len(text)} characters" in result


@pytest.mark.asyncio
async def test_type_text_sends_return_for_newlines(monkeypatch, trusted, toolkit):
    keys = []
    monkeypatch.setattr(mod, "_post_text", lambda chunk: True)
    monkeypatch.setattr(
        mod, "_post_key", lambda code, flags, down: keys.append((code, down))
    )

    await _raw(toolkit.type_text)(toolkit, "one\ntwo")
    assert (36, True) in keys and (36, False) in keys


@pytest.mark.asyncio
async def test_screenshot_rejects_bad_region(trusted, toolkit):
    result = await _raw(toolkit.desktop_screenshot)(toolkit, region="10,20")
    assert "x,y,width,height" in result


@pytest.mark.asyncio
async def test_screenshot_reports_capture_failure(monkeypatch, trusted, toolkit):
    async def fake_run(args, timeout=30):
        return 1, b"", b"no permission"

    monkeypatch.setattr(mod, "displays", lambda: [])
    monkeypatch.setattr(toolkit, "_run", fake_run)
    result = await _raw(toolkit.desktop_screenshot)(toolkit)
    assert "screencapture failed" in result
    assert "no permission" in result
