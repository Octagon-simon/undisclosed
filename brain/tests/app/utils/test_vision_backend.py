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

import json
from types import SimpleNamespace

import pytest

from app.utils import vision_backend


def _row(platform, model_type, *, prefer=False, key="k", url=""):
    return {
        "provider_name": platform,
        "model_type": model_type,
        "api_key": key,
        "endpoint_url": url,
        "prefer": prefer,
        "encrypted_config": {
            "model_platform": platform,
            "model_type": model_type,
        },
    }


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    vision_backend._CACHE.clear()
    monkeypatch.delenv("UNDISCLOSED_VISION_MODEL", raising=False)
    monkeypatch.delenv("VISION_MODEL", raising=False)
    providers = tmp_path / "providers.json"
    monkeypatch.setattr(vision_backend, "_providers_path", lambda: providers)
    return providers


def _write(path, rows):
    path.write_text(json.dumps(rows), encoding="utf-8")


def test_resolve_skips_preferred_text_model(_reset):
    _write(
        _reset,
        [
            _row("deepseek", "deepseek-v4-flash", prefer=True),
            _row("deepseek", "deepseek-v4-flash-vision-exp"),
        ],
    )
    config = vision_backend.resolve_vision_provider()
    assert config is not None
    assert config["model_type"] == "deepseek-v4-flash-vision-exp"
    assert config["model_platform"] == "deepseek"


def test_resolve_uses_explicit_override(_reset, monkeypatch):
    _write(
        _reset,
        [
            _row("deepseek", "deepseek-v4-flash-vision-exp"),
            _row("openai", "gpt-4o"),
        ],
    )
    monkeypatch.setenv("UNDISCLOSED_VISION_MODEL", "gpt-4o")
    config = vision_backend.resolve_vision_provider()
    assert config is not None
    assert config["model_type"] == "gpt-4o"


def test_resolve_returns_none_when_no_vision_model(_reset):
    _write(_reset, [_row("deepseek", "deepseek-chat", prefer=True)])
    assert vision_backend.resolve_vision_provider() is None


def test_vision_backend_prefers_configured_model(monkeypatch, _reset):
    _write(_reset, [_row("deepseek", "deepseek-v4-flash-vision-exp")])
    sentinel = object()
    monkeypatch.setattr(
        vision_backend, "_create_backend", lambda config: sentinel
    )
    text_agent = SimpleNamespace(
        model_backend=SimpleNamespace(model_type="deepseek-chat")
    )
    assert vision_backend.vision_backend_for(text_agent) is sentinel


def test_vision_backend_falls_back_to_multimodal_agent(_reset, monkeypatch):
    _write(_reset, [])
    backend = SimpleNamespace(model_type="gpt-4o", model_platform="openai")
    agent = SimpleNamespace(model_backend=backend)
    assert vision_backend.vision_backend_for(agent) is backend


def test_vision_backend_never_returns_text_only_agent(_reset):
    _write(_reset, [])
    agent = SimpleNamespace(
        model_backend=SimpleNamespace(model_type="deepseek-chat")
    )
    assert vision_backend.vision_backend_for(agent) is None


def test_vision_backend_is_cached(monkeypatch, _reset):
    _write(_reset, [_row("deepseek", "deepseek-v4-flash-vision-exp")])
    calls = []

    def build(config):
        calls.append(config)
        return SimpleNamespace(model_type=config["model_type"])

    monkeypatch.setattr(vision_backend, "_create_backend", build)
    first = vision_backend.vision_backend_for(None)
    second = vision_backend.vision_backend_for(None)
    assert first is second
    assert len(calls) == 1
