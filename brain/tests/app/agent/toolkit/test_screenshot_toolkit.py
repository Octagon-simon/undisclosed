# Copyright (c) 2026 Simon Ugorji
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

from types import SimpleNamespace

import pytest
from camel.toolkits import ScreenshotToolkit as BaseScreenshotToolkit
from PIL import Image

import app.agent.toolkit.screenshot_toolkit as screenshot_module
from app.agent.toolkit.screenshot_toolkit import ScreenshotToolkit


class _Lock:
    async def put_queue(self, data):
        return None


@pytest.fixture(autouse=True)
def stub_task_lock(monkeypatch):
    import app.utils.listen.toolkit_listen as toolkit_listen

    monkeypatch.setattr(toolkit_listen, "get_task_lock", lambda _tid: _Lock())


@pytest.fixture
def toolkit(tmp_path):
    return ScreenshotToolkit(
        "task-1", "Single Agent", working_directory=str(tmp_path)
    )


def _tools(toolkit):
    return {tool.get_function_name(): tool for tool in toolkit.get_tools()}


@pytest.mark.unit
def test_capability_is_named_for_reading_images():
    assert ScreenshotToolkit.toolkit_name() == "Image Reader"


@pytest.mark.unit
def test_desktop_capture_is_exposed_by_default(toolkit):
    assert set(_tools(toolkit)) == {
        "read_image",
        "take_screenshot_and_read_image",
    }


@pytest.mark.unit
def test_desktop_capture_can_be_disabled(tmp_path):
    tk = ScreenshotToolkit(
        "task-1",
        "Single Agent",
        working_directory=str(tmp_path),
        enable_desktop_capture=False,
    )
    assert set(_tools(tk)) == {"read_image"}
    assert "disabled" in tk.take_screenshot_and_read_image("screen.png")


@pytest.mark.unit
def test_tool_descriptions_separate_page_from_file(toolkit):
    tools = _tools(toolkit)
    reader = tools["read_image"].get_function_description()
    capture = tools["take_screenshot_and_read_image"].get_function_description()

    assert "already exists on disk" in reader
    assert "capture_page" in reader
    assert "desktop screen" in capture
    assert "capture_page" in capture


def _png(tmp_path):
    path = tmp_path / "shot.png"
    Image.new("RGB", (4, 4), "red").save(path)
    return str(path)


def _vision_toolkit(toolkit):
    toolkit._agent = SimpleNamespace(step_timeout=11.0)
    return toolkit


class _Response:
    def __init__(self, msg=None, msgs=None):
        self.msg = msg
        self.msgs = msgs


class _RecordingVisionAgent:
    calls = []
    response = None

    def __init__(self, **kwargs):
        _RecordingVisionAgent.calls.append(kwargs)

    def step(self, _message):
        return _RecordingVisionAgent.response


@pytest.fixture
def vision_agent(monkeypatch):
    _RecordingVisionAgent.calls = []
    _RecordingVisionAgent.response = _Response(
        msg=SimpleNamespace(content="a red square")
    )
    monkeypatch.setattr(screenshot_module, "ChatAgent", _RecordingVisionAgent)
    monkeypatch.setattr(
        screenshot_module, "vision_backend_for", lambda _agent: object()
    )
    return _RecordingVisionAgent


@pytest.mark.unit
def test_default_working_directory_comes_from_config(monkeypatch, tmp_path):
    monkeypatch.setattr(
        screenshot_module, "env", lambda _key, _default: str(tmp_path)
    )
    tk = ScreenshotToolkit("task-1", "Single Agent")
    assert tk.screenshots_dir == tmp_path


@pytest.mark.unit
def test_read_image_without_registered_agent(toolkit):
    assert "No agent registered" in toolkit.read_image("whatever.png")


@pytest.mark.unit
def test_read_image_missing_file(toolkit):
    _vision_toolkit(toolkit)
    result = toolkit.read_image("does-not-exist.png")
    assert "not found" in result
    assert "does-not-exist.png" in result


@pytest.mark.unit
def test_read_image_without_vision_model(toolkit, monkeypatch, tmp_path):
    _vision_toolkit(toolkit)
    monkeypatch.setattr(
        screenshot_module, "vision_backend_for", lambda _agent: None
    )
    assert "no vision-capable model" in toolkit.read_image(_png(tmp_path))


@pytest.mark.unit
def test_read_image_returns_vision_answer(toolkit, vision_agent, tmp_path):
    result = _vision_toolkit(toolkit).read_image(_png(tmp_path), "what is it?")

    assert result == "a red square"
    call = vision_agent.calls[0]
    assert call["tools"] == []
    assert call["step_timeout"] == 11.0
    assert call["external_tools"] is None
    assert call["toolkits_to_register_agent"] is None


@pytest.mark.unit
def test_read_image_falls_back_to_msgs(toolkit, vision_agent, tmp_path):
    vision_agent.response = _Response(msgs=[SimpleNamespace(content="from msgs")])
    assert _vision_toolkit(toolkit).read_image(_png(tmp_path)) == "from msgs"


@pytest.mark.unit
def test_read_image_reports_empty_response(toolkit, vision_agent, tmp_path):
    vision_agent.response = _Response()
    result = _vision_toolkit(toolkit).read_image(_png(tmp_path))
    assert "empty response" in result


@pytest.mark.unit
def test_read_image_swallows_vision_failure(toolkit, monkeypatch, tmp_path):
    class _FailingVisionAgent(_RecordingVisionAgent):
        def step(self, _message):
            raise RuntimeError("model offline")

    monkeypatch.setattr(screenshot_module, "ChatAgent", _FailingVisionAgent)
    result = _vision_toolkit(toolkit).read_image(_png(tmp_path))
    assert "model offline" in result


@pytest.mark.unit
def test_desktop_capture_passes_result_through(toolkit, monkeypatch):
    def fake(_self, **_kwargs):
        return "Screenshot saved to /tmp/shot.png"

    monkeypatch.setattr(
        BaseScreenshotToolkit, "take_screenshot_and_read_image", fake
    )
    result = toolkit.take_screenshot_and_read_image("shot.png")
    assert result == "Screenshot saved to /tmp/shot.png"


@pytest.mark.unit
def test_desktop_capture_adds_macos_permission_hint(toolkit, monkeypatch):
    def fake(_self, **_kwargs):
        return "Error taking screenshot: not authorized"

    monkeypatch.setattr(
        BaseScreenshotToolkit, "take_screenshot_and_read_image", fake
    )
    monkeypatch.setattr(screenshot_module.sys, "platform", "darwin")

    result = toolkit.take_screenshot_and_read_image("shot.png")

    assert result.startswith("Error taking screenshot: not authorized")
    assert "Screen Recording" in result
