# Copyright (c) 2026 Simon Ugorji
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

import io
import platform
from pathlib import Path

import pytest
from PIL import Image

from app.agent.toolkit.iris_toolkit import IrisToolkit

# A real iris process needs a browser, so the subprocess boundary (`_run`) is
# faked: these tests cover argument building, output resolution, and how the
# result is shaped for a vision vs text-only model.

_buf = io.BytesIO()
Image.new("RGB", (4, 4), (255, 255, 255)).save(_buf, "PNG")
PNG = _buf.getvalue()


class _Lock:
    async def put_queue(self, data):
        return None


@pytest.fixture(autouse=True)
def stub_task_lock(monkeypatch):
    import app.utils.listen.toolkit_listen as toolkit_listen

    monkeypatch.setattr(toolkit_listen, "get_task_lock", lambda _tid: _Lock())


@pytest.fixture
def toolkit(tmp_path):
    tk = IrisToolkit(
        "task-1", working_directory=str(tmp_path), model_type="gpt-4o"
    )
    tk._binary = str(tmp_path / "iris")
    return tk


def _fake_run(calls, error=None):
    report = {
        "status": "ok",
        "css_width": 800,
        "css_height": 600,
        "scale": 2.0,
    }

    async def run(_self, args):
        calls.append(args)
        if error is None:
            Path(args[args.index("--out") + 1]).write_bytes(PNG)
            return report, None
        return None, error

    return run


@pytest.mark.unit
def test_toolkit_name_and_tool_surface(toolkit):
    assert IrisToolkit.toolkit_name() == "Page Screenshots"
    assert [t.get_function_name() for t in toolkit.get_tools()] == [
        "capture_page"
    ]


@pytest.mark.unit
def test_resolve_binary_honors_env_override(monkeypatch, tmp_path):
    binary = tmp_path / "custom-iris"
    binary.write_bytes(PNG)
    monkeypatch.setenv("IRIS_BIN", str(binary))
    assert IrisToolkit.resolve_binary() == str(binary)


@pytest.mark.unit
def test_resolve_binary_finds_bundled_resources_path(monkeypatch, tmp_path):
    import app.agent.toolkit.iris_toolkit as iris_module

    platform_dir = f"{platform.system().lower()}-{platform.machine().lower()}"
    binary = (
        tmp_path / "resources" / "binaries" / "iris" / platform_dir / "iris"
    )
    binary.parent.mkdir(parents=True)
    binary.write_bytes(PNG)

    monkeypatch.delenv("IRIS_BIN", raising=False)
    monkeypatch.setattr(iris_module, "_candidate_roots", lambda: [tmp_path])
    monkeypatch.setattr(iris_module.shutil, "which", lambda _name: None)

    assert IrisToolkit.resolve_binary() == str(binary)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_capture_reports_path_and_attaches_image(
    monkeypatch, toolkit, tmp_path
):
    calls = []
    monkeypatch.setattr(IrisToolkit, "_run", _fake_run(calls))

    result = await toolkit.capture_page(
        "http://localhost:3000", out=str(tmp_path / "shots")
    )

    assert len(calls) == 1
    assert result.images and result.images[0].startswith("data:image/png;base64,")
    assert "800x600" in result.text
    assert "shots" in result.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_selector_capture_passes_crop_flags(monkeypatch, toolkit):
    calls = []
    monkeypatch.setattr(IrisToolkit, "_run", _fake_run(calls))

    await toolkit.capture_page(
        "http://localhost:3000", selector="#hero", padding=12
    )

    args = calls[0]
    assert args[args.index("--selector") + 1] == "#hero"
    assert args[args.index("--padding") + 1] == "12"
    assert "--full" not in args


@pytest.mark.unit
@pytest.mark.asyncio
async def test_full_page_flag(monkeypatch, toolkit):
    calls = []
    monkeypatch.setattr(IrisToolkit, "_run", _fake_run(calls))

    await toolkit.capture_page("http://localhost:3000", full_page=True)

    assert "--full" in calls[0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_multi_viewport_dark_runs_one_capture_each(
    monkeypatch, toolkit, tmp_path
):
    calls = []
    monkeypatch.setattr(IrisToolkit, "_run", _fake_run(calls))

    result = await toolkit.capture_page(
        "http://localhost:3000",
        sizes=["desktop", "iphone"],
        dark=True,
        out=str(tmp_path / "shots"),
    )

    assert len(calls) == 2
    names = sorted(Path(a[a.index("--out") + 1]).name for a in calls)
    assert names == [
        "localhost-3000-desktop-dark.png",
        "localhost-3000-iphone-dark.png",
    ]
    assert len(result.images) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_text_only_model_gets_paths_not_images(
    monkeypatch, toolkit, tmp_path
):
    calls = []
    monkeypatch.setattr(IrisToolkit, "_run", _fake_run(calls))
    monkeypatch.setattr(
        "app.agent.toolkit.iris_toolkit.vision_backend_for", lambda _agent: None
    )
    toolkit.model_type = "deepseek-chat"

    result = await toolkit.capture_page(
        "http://localhost:3000", out=str(tmp_path / "s")
    )

    assert isinstance(result, str)
    assert "No images attached" in result
    assert "deepseek-chat is not known to accept image input" in result
    assert "no vision model is configured" in result
    assert "read_image" in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_read_image_false_reports_the_opt_out(monkeypatch, toolkit):
    calls = []
    monkeypatch.setattr(IrisToolkit, "_run", _fake_run(calls))

    result = await toolkit.capture_page(
        "http://localhost:3000", read_image=False
    )

    assert isinstance(result, str)
    assert "No images attached (read_image=False)" in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_vision_model_names_attached_count(
    monkeypatch, toolkit, tmp_path
):
    calls = []
    monkeypatch.setattr(IrisToolkit, "_run", _fake_run(calls))

    result = await toolkit.capture_page(
        "http://localhost:3000",
        sizes=["desktop", "iphone"],
        out=str(tmp_path / "s"),
    )

    assert "Images attached to context: 2." in result.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_light_capture_goes_through_scheme_wrapper(monkeypatch, toolkit):
    calls = []
    monkeypatch.setattr(IrisToolkit, "_run", _fake_run(calls))
    monkeypatch.setattr(
        "app.agent.toolkit.iris_toolkit._resolve_chrome",
        lambda: "/real/chrome",
    )
    monkeypatch.setattr(
        "app.agent.toolkit.iris_toolkit._light_chrome_wrapper",
        lambda _chrome: "/tmp/light-wrapper.sh",
    )

    await toolkit.capture_page("http://localhost:3000")

    args = calls[0]
    assert args[args.index("--chrome") + 1] == "/tmp/light-wrapper.sh"
    assert "--dark" not in args


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dark_capture_keeps_real_chrome(monkeypatch, toolkit):
    calls = []
    monkeypatch.setattr(IrisToolkit, "_run", _fake_run(calls))
    monkeypatch.setattr(
        "app.agent.toolkit.iris_toolkit._resolve_chrome",
        lambda: "/real/chrome",
    )

    await toolkit.capture_page("http://localhost:3000", dark=True)

    args = calls[0]
    assert args[args.index("--chrome") + 1] == "/real/chrome"
    assert "--dark" in args


@pytest.mark.unit
def test_light_wrapper_pins_the_light_scheme(monkeypatch, tmp_path):
    import app.agent.toolkit.iris_toolkit as iris_module

    monkeypatch.setattr(
        iris_module.tempfile, "gettempdir", lambda: str(tmp_path)
    )
    chrome = "/Apps/Google Chrome For Testing.app/Contents/MacOS/Chrome"

    wrapper = iris_module._light_chrome_wrapper(chrome)
    if wrapper is None:  # Windows skips the wrapper entirely
        pytest.skip("light wrapper is POSIX-only")

    body = Path(wrapper).read_text()
    assert "--blink-settings=preferredColorScheme=1" in body
    assert f"exec '{chrome}'" in body
    assert Path(wrapper).stat().st_mode & 0o111


@pytest.mark.unit
@pytest.mark.asyncio
async def test_selector_and_full_page_conflict(toolkit):
    result = await toolkit.capture_page(
        "http://localhost:3000", selector="#hero", full_page=True
    )

    assert isinstance(result, str)
    assert "mutually exclusive" in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_capture_failure_is_reported(monkeypatch, toolkit):
    calls = []
    monkeypatch.setattr(
        IrisToolkit, "_run", _fake_run(calls, error="selector never appeared")
    )

    result = await toolkit.capture_page(
        "http://localhost:3000", selector="#nope"
    )

    assert isinstance(result, str)
    assert "capture failed" in result
    assert "selector never appeared" in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_binary_fails_soft(monkeypatch, tmp_path):
    monkeypatch.setattr(
        IrisToolkit, "resolve_binary", classmethod(lambda _cls: None)
    )
    tk = IrisToolkit("task-1", working_directory=str(tmp_path))

    result = await tk.capture_page("http://localhost:3000")

    assert isinstance(result, str)
    assert "iris" in result
    assert "not installed" in result


class _VisionResponse:
    def __init__(self, content):
        self.msg = type("Msg", (), {"content": content})()


class _FakeVisionAgent:
    calls: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def astep(self, message):
        _FakeVisionAgent.calls.append((self.kwargs, message))
        return _VisionResponse("  Heading ORACLE-7F3A, dark background.  ")


class _FakeBackend:
    model_type = "deepseek-v4-flash-vision-exp"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_text_only_chat_model_is_read_by_the_vision_model(
    monkeypatch, toolkit, tmp_path
):
    import app.agent.toolkit.iris_toolkit as iris_module

    calls = []
    monkeypatch.setattr(IrisToolkit, "_run", _fake_run(calls))
    monkeypatch.setattr(
        iris_module, "vision_backend_for", lambda _agent: _FakeBackend()
    )
    monkeypatch.setattr(iris_module, "ChatAgent", _FakeVisionAgent)
    _FakeVisionAgent.calls = []
    toolkit.model_type = "deepseek-v4-flash"
    toolkit._agent = object()

    result = await toolkit.capture_page(
        "http://localhost:3000",
        sizes=["desktop", "iphone"],
        out=str(tmp_path / "s"),
    )

    assert isinstance(result, str)
    assert "No images attached: deepseek-v4-flash is not known" in result
    assert "deepseek-v4-flash-vision-exp read them" in result
    assert "ORACLE-7F3A" in result
    assert len(_FakeVisionAgent.calls) == 2
    kwargs, message = _FakeVisionAgent.calls[0]
    assert kwargs["tools"] == []
    assert isinstance(kwargs["model"], _FakeBackend)
    assert len(message.image_list) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_vision_fallback_runs_without_a_bound_agent(
    monkeypatch, toolkit, tmp_path
):
    import app.agent.toolkit.iris_toolkit as iris_module

    calls = []
    monkeypatch.setattr(IrisToolkit, "_run", _fake_run(calls))
    monkeypatch.setattr(
        iris_module, "vision_backend_for", lambda _agent: _FakeBackend()
    )
    monkeypatch.setattr(iris_module, "ChatAgent", _FakeVisionAgent)
    toolkit.model_type = "deepseek-v4-flash"
    toolkit._agent = None

    result = await toolkit.capture_page(
        "http://localhost:3000", out=str(tmp_path / "s")
    )

    assert isinstance(result, str)
    assert "deepseek-v4-flash-vision-exp read them" in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_text_only_model_without_a_vision_model_says_so(
    monkeypatch, toolkit
):
    import app.agent.toolkit.iris_toolkit as iris_module

    calls = []
    monkeypatch.setattr(IrisToolkit, "_run", _fake_run(calls))
    monkeypatch.setattr(iris_module, "vision_backend_for", lambda _agent: None)
    toolkit.model_type = "deepseek-v4-flash"
    toolkit._agent = object()

    result = await toolkit.capture_page("http://localhost:3000")

    assert isinstance(result, str)
    assert "no vision model is configured" in result
    assert "read_image" in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_vision_failure_falls_back_to_the_plain_message(
    monkeypatch, toolkit
):
    import app.agent.toolkit.iris_toolkit as iris_module

    calls = []
    monkeypatch.setattr(IrisToolkit, "_run", _fake_run(calls))

    def boom(_agent):
        raise RuntimeError("no provider config")

    monkeypatch.setattr(iris_module, "vision_backend_for", boom)
    toolkit.model_type = "deepseek-v4-flash"
    toolkit._agent = object()

    result = await toolkit.capture_page("http://localhost:3000")

    assert isinstance(result, str)
    assert "not known to accept image input" in result


class _FailingVisionAgent:
    def __init__(self, **_kwargs):
        pass

    async def astep(self, _message):
        raise RuntimeError("provider returned 500")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_vision_read_failure_is_reported_not_hidden(
    monkeypatch, toolkit, tmp_path
):
    import app.agent.toolkit.iris_toolkit as iris_module

    calls = []
    monkeypatch.setattr(IrisToolkit, "_run", _fake_run(calls))
    monkeypatch.setattr(
        iris_module, "vision_backend_for", lambda _agent: _FakeBackend()
    )
    monkeypatch.setattr(iris_module, "ChatAgent", _FailingVisionAgent)
    toolkit.model_type = "deepseek-v4-flash"
    toolkit._agent = object()

    result = await toolkit.capture_page(
        "http://localhost:3000", out=str(tmp_path / "s")
    )

    assert isinstance(result, str)
    assert "deepseek-v4-flash-vision-exp returned nothing" in result
    assert "read_image" in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_undecodable_shot_is_reported(monkeypatch, toolkit, tmp_path):
    import app.agent.toolkit.iris_toolkit as iris_module

    async def run(_self, args):
        Path(args[args.index("--out") + 1]).write_bytes(b"not a png")
        return {"status": "ok"}, None

    monkeypatch.setattr(IrisToolkit, "_run", run)
    monkeypatch.setattr(
        iris_module, "vision_backend_for", lambda _agent: _FakeBackend()
    )
    toolkit.model_type = "deepseek-v4-flash"
    toolkit._agent = object()

    result = await toolkit.capture_page(
        "http://localhost:3000", out=str(tmp_path / "s")
    )

    assert isinstance(result, str)
    assert "returned nothing" in result
