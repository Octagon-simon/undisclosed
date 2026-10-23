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

"""The model used for image work (read_image, image captions).

The chat model is often text-only (a coding or cheap model), so tools that
look at a picture cannot reuse it: sending an image block to a text model
either 400s or gets silently dropped. Resolve a vision-capable provider from
the local provider config instead, and only fall back to the agent's own
backend when that backend can actually see images.

`UNDISCLOSED_VISION_MODEL` pins an exact configured model id (for example
`deepseek-v4-flash-vision-exp`); otherwise the first vision-capable provider
wins, with ids containing "vision" preferred over a generic platform match.
"""

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from app.utils.model_capabilities import model_supports_vision

logger = logging.getLogger("vision_backend")

_CACHE: dict[tuple[str, str, str, str], Any] = {}
_LOCK = threading.Lock()


def _providers_path() -> Path:
    return Path.home() / ".undisclosed" / "providers.json"


def _load_providers() -> list[dict]:
    try:
        rows = json.loads(_providers_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _config_of(row: dict) -> dict | None:
    config = row.get("encrypted_config") or {}
    if not isinstance(config, dict):
        config = {}
    platform = config.get("model_platform") or row.get("provider_name") or ""
    model_type = config.get("model_type") or row.get("model_type") or ""
    if not platform or not model_type:
        return None
    return {
        "model_platform": str(platform),
        "model_type": str(model_type),
        "api_key": str(row.get("api_key") or ""),
        "api_url": str(row.get("endpoint_url") or ""),
    }


def resolve_vision_provider() -> dict | None:
    """Return the configured provider to use for image input, or None."""
    rows = _load_providers()
    override = (
        os.environ.get("UNDISCLOSED_VISION_MODEL")
        or os.environ.get("VISION_MODEL")
        or ""
    ).strip()

    best: tuple[int, dict] | None = None
    for row in rows:
        config = _config_of(row)
        if config is None:
            continue
        model_type = config["model_type"]
        if override:
            if model_type != override:
                continue
            score = 100
        else:
            if not model_supports_vision(
                config["model_platform"], model_type
            ):
                continue
            score = 10
            if "vision" in model_type.lower():
                score += 5
            if row.get("prefer"):
                score += 1
        if best is None or score > best[0]:
            best = (score, config)
    return best[1] if best else None


def _backend_sees_images(backend: Any) -> bool:
    if backend is None:
        return False
    model_type = getattr(backend, "model_type", None)
    value = getattr(model_type, "value", model_type)
    return model_supports_vision(
        getattr(backend, "model_platform", None), str(value or "")
    )


def _create_backend(config: dict) -> Any:
    from camel.models import ModelFactory

    return ModelFactory.create(
        model_platform=config["model_platform"],
        model_type=config["model_type"],
        api_key=config["api_key"] or None,
        url=config["api_url"] or None,
        timeout=600,
    )


def vision_backend_for(agent: Any = None) -> Any:
    """A backend that accepts image blocks, or None when none is available.

    Prefers the configured image model, then the agent's own model when it is
    multimodal. Never returns a text-only backend, because the caller is about
    to send it an image.
    """
    config = resolve_vision_provider()
    if config is not None:
        cache_key = (
            config["model_platform"],
            config["model_type"],
            config["api_key"],
            config["api_url"],
        )
        with _LOCK:
            backend = _CACHE.get(cache_key)
        if backend is None:
            try:
                backend = _create_backend(config)
            except Exception:
                logger.warning(
                    "Could not build image model %s/%s",
                    config["model_platform"],
                    config["model_type"],
                    exc_info=True,
                )
                backend = None
            else:
                with _LOCK:
                    _CACHE[cache_key] = backend
        if backend is not None:
            return backend

    fallback = getattr(agent, "model_backend", None)
    return fallback if _backend_sees_images(fallback) else None
