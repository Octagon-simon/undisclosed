# Copyright (c) 2026 Simon Ugorji
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

import platform
from pathlib import Path

import pytest

from app.agent.toolkit.iris_toolkit import IrisToolkit

# A real iris process needs a browser, so the subprocess boundary (`_run`) is
# faked: these tests cover argument building, output resolution, and how the
# result is shaped for a vision vs text-only model.

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


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
async def test_text_only_model_gets_paths_not_images(monkeypatch, toolkit):
    calls = []
    monkeypatch.setattr(IrisToolkit, "_run", _fake_run(calls))
    toolkit.model_type = "deepseek-chat"

    result = await toolkit.capture_page("http://localhost:3000")

    assert isinstance(result, str)
    assert "read_image" in result


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
