# ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========
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

import io

import pytest
from PIL import Image

from app.agent.toolkit import app_capture_toolkit as mod
from app.agent.toolkit.app_capture_toolkit import AppCaptureToolkit

pytestmark = pytest.mark.unit


def _raw(fn):
    """Strip the listen_toolkit wrappers, which require a live task lock."""
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _png(width: int = 40, height: int = 30) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def toolkit(tmp_path):
    return AppCaptureToolkit(
        api_task_id="test-task", working_directory=str(tmp_path)
    )


def _window(number: int, owner: str, title: str = "", size=(100, 100)):
    return {
        "number": number,
        "pid": 1000 + number,
        "owner": owner,
        "title": title,
        "bounds": (0.0, 0.0, float(size[0]), float(size[1])),
    }


def test_available_backends_empty_when_no_tool_exists(monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(mod, "_adb_binary", lambda: None)

    assert AppCaptureToolkit.available_backends() == []


def test_pick_window_prefers_largest_exact_owner(toolkit, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        mod,
        "list_windows",
        lambda: [
            _window(1, "Notes", "Small", (200, 200)),
            _window(2, "Notes", "Big", (900, 700)),
            _window(3, "Slack", "Slack"),
        ],
    )
    picked = toolkit._pick_window("notes", "")

    assert picked["kind"] == "window"
    assert picked["number"] == 2
    assert picked["label"].startswith("Notes")


def test_pick_window_uses_title_hint(toolkit, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        mod,
        "list_windows",
        lambda: [
            _window(2, "Notes", "Big", (900, 700)),
            _window(4, "Notes", "Scratch", (300, 300)),
        ],
    )
    picked = toolkit._pick_window("notes", "scratch")

    assert picked["number"] == 4


def test_pick_window_by_number_and_pid(toolkit, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        mod,
        "list_windows",
        lambda: [_window(7, "Notes"), _window(8, "Slack")],
    )
    tk = toolkit

    assert tk._pick_window("8", "")["number"] == 8
    assert tk._pick_window("pid:1007", "")["number"] == 7


@pytest.mark.asyncio
async def test_resolve_prefers_simulator_by_name(toolkit, monkeypatch):
    async def sims():
        return [{"udid": "ABC-123", "name": "iPhone 17", "runtime": "iOS-26-5"}]

    async def none():
        return []

    monkeypatch.setattr(mod, "list_simulators", sims)
    monkeypatch.setattr(mod, "list_android_devices", none)
    monkeypatch.setattr(mod.platform, "system", lambda: "Linux")

    picked = await toolkit._resolve("iphone 17", "auto", "")

    assert picked["kind"] == "simulator"
    assert picked["udid"] == "ABC-123"


@pytest.mark.asyncio
async def test_resolve_prefers_android_serial(toolkit, monkeypatch):
    async def devices():
        return [{"serial": "emulator-5554", "model": "sdk_gphone", "emulator": True}]

    async def none():
        return []

    monkeypatch.setattr(mod, "list_android_devices", devices)
    monkeypatch.setattr(mod, "list_simulators", none)

    picked = await toolkit._resolve("5554", "auto", "")

    assert picked["kind"] == "android"
    assert picked["serial"] == "emulator-5554"


@pytest.mark.asyncio
async def test_resolve_empty_target_refuses_to_guess(toolkit, monkeypatch):
    async def none():
        return []

    monkeypatch.setattr(mod, "list_simulators", none)
    monkeypatch.setattr(mod, "list_android_devices", none)
    monkeypatch.setattr(mod.platform, "system", lambda: "Linux")

    result = await toolkit._resolve("", "auto", "")

    assert isinstance(result, str)
    assert "needs a target" in result


@pytest.mark.asyncio
async def test_resolve_desktop_refuses_off_macos(toolkit, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Linux")

    result = await toolkit._resolve("desktop", "desktop", "")

    assert isinstance(result, str)
    assert "only available on macOS" in result


@pytest.mark.asyncio
async def test_resolve_desktop_on_macos(toolkit, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(mod, "_screencapture_binary", lambda: "/usr/sbin/screencapture")

    picked = await toolkit._resolve("", "desktop", "")

    assert picked["kind"] == "desktop"


@pytest.mark.asyncio
async def test_capture_window_failure_maps_to_permission_help(
    toolkit, tmp_path, monkeypatch
):
    async def failed(args, timeout=30):
        return 1, b"", b"could not create image from window"

    monkeypatch.setattr(mod, "_run", failed)
    monkeypatch.setattr(mod, "_screencapture_binary", lambda: "/usr/sbin/screencapture")

    error = await toolkit._capture(
        {"kind": "window", "number": 7}, tmp_path / "shot.png"
    )

    assert "Screen Recording" in error


@pytest.mark.asyncio
async def test_capture_android_writes_png_bytes(toolkit, tmp_path, monkeypatch):
    payload = _png()

    async def ok(args, timeout=30):
        assert args[-3:] == ["exec-out", "screencap", "-p"]
        return 0, payload, b""

    monkeypatch.setattr(mod, "_adb_binary", lambda: "/fake/adb")
    monkeypatch.setattr(mod, "_run", ok)

    target = tmp_path / "android.png"
    error = await toolkit._capture(
        {"kind": "android", "serial": "emulator-5554"}, target
    )

    assert error is None
    assert target.read_bytes() == payload


@pytest.mark.asyncio
async def test_capture_app_reports_backend_and_size(toolkit, tmp_path, monkeypatch):
    async def sims():
        return [{"udid": "ABC-123", "name": "iPhone 17", "runtime": "iOS-26-5"}]

    async def fake_capture(picked, path):
        path.write_bytes(_png())
        return None

    monkeypatch.setattr(mod, "list_simulators", sims)
    monkeypatch.setattr(AppCaptureToolkit, "_capture", staticmethod(fake_capture))

    text = await _raw(AppCaptureToolkit.capture_app)(
        toolkit, "iPhone 17", "simulator", "", str(tmp_path / "app.png"), False
    )

    assert "via iOS Simulator (iOS-26-5)" in text
    assert "40x30" in text
    assert "read_image=False" in text


@pytest.mark.asyncio
async def test_list_capture_targets_flags_missing_permission(toolkit, monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(mod, "list_windows", lambda: [_window(1, "Notes")])
    monkeypatch.setattr(mod, "screen_capture_allowed", lambda: False)
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(mod, "_adb_binary", lambda: None)

    async def none():
        return []

    monkeypatch.setattr(mod, "list_simulators", none)
    monkeypatch.setattr(mod, "list_android_devices", none)

    text = await _raw(AppCaptureToolkit.list_capture_targets)(toolkit)

    assert "Screen Recording NOT granted" in text
    assert "- Notes" in text
    assert "xcrun not available" in text
    assert "adb not found" in text


def test_single_agent_prompt_points_at_both_cameras():
    """The single agent owns both cameras, so its prompt must name them."""
    from app.agent.prompt import BROWSER_SYS_PROMPT, SINGLE_AGENT_SYS_PROMPT

    prompt = SINGLE_AGENT_SYS_PROMPT.format(
        platform_system="Darwin",
        platform_machine="arm64",
        working_directory="/tmp",
        now_str="now",
    )

    assert "`capture_app`" in prompt
    assert "`list_capture_targets`" in prompt
    assert "`capture_page`" in prompt
    assert "Page Screenshots" in prompt
    # browser sub-agent has neither camera capability, so guidance there is
    # dead text it cannot act on
    for capability in ("App Screenshots", "Page Screenshots"):
        assert capability not in BROWSER_SYS_PROMPT
    assert "`capture_page`" not in BROWSER_SYS_PROMPT


def test_single_agent_prompt_covers_screenshot_to_code():
    """The skill is gone, so its block-then-fidelity method lives in the prompt."""
    from app.agent.prompt import SINGLE_AGENT_SYS_PROMPT

    prompt = SINGLE_AGENT_SYS_PROMPT.format(
        platform_system="Darwin",
        platform_machine="arm64",
        working_directory="/tmp",
        now_str="now",
    )

    for phrase in (
        "header/nav, hero, content rows",
        "semantic HTML5",
        ":root` custom properties",
        "under 640px",
        "do not invent placeholder copy",
    ):
        assert phrase in prompt
