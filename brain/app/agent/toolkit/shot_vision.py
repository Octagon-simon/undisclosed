# Copyright (c) 2026 Simon Ugorji
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Shared "can we see the shot" helpers for the camera toolkits.

The page camera and the app camera both end up holding PNGs on disk and face
the same decision: attach them when the chat model accepts image input,
otherwise borrow the configured image model to describe them.
"""

import asyncio
import base64
import logging
from pathlib import Path

from camel.agents import ChatAgent
from camel.messages import BaseMessage
from PIL import Image

from app.utils.model_capabilities import model_supports_vision
from app.utils.vision_backend import vision_backend_for

logger = logging.getLogger("shot_vision")

MAX_ATTACHED = 3

READ_PROMPT = (
    "Describe this screenshot so a model that cannot see images can reason "
    "about it. In 3-5 sentences cover: what application or screen this is, "
    "the overall layout and the visible headings and key text, the color "
    "scheme (light or dark) with the main colors, and any obvious visual "
    "defects such as overlapping, clipped, or misaligned content, missing "
    "glyphs, or large empty regions. Be specific and factual."
)


def agent_sees_images(
    agent,
    model_type: str | None = None,
    model_platform: str | None = None,
) -> bool:
    """Whether the chat model behind `agent` accepts image input."""
    if model_type or model_platform:
        return model_supports_vision(model_platform, model_type)
    try:
        # Only reached when the caller got no model identity. Unwrap ModelType
        # so enum and string backends match against the same markers.
        backend = getattr(agent, "model_backend", None)
        raw = getattr(backend, "model_type", None)
        value = getattr(raw, "value", raw)
        return model_supports_vision(None, str(value) if value else None)
    except Exception:
        return False


def load_images(shots: list[dict], limit: int = MAX_ATTACHED) -> list[str]:
    """Data URLs for the first `limit` shots, skipping unreadable files."""
    images: list[str] = []
    for shot in shots[:limit]:
        try:
            data = Path(shot["path"]).read_bytes()
        except OSError:
            continue
        if not data:
            continue
        suffix = Path(shot["path"]).suffix.lower().lstrip(".") or "png"
        mime = "jpeg" if suffix in {"jpg", "jpeg"} else suffix
        images.append(f"data:image/{mime};base64," + base64.b64encode(data).decode())
    return images


async def describe_images(
    agent,
    shots: list[dict],
    prompt: str = READ_PROMPT,
    limit: int = MAX_ATTACHED,
) -> tuple[str, str] | None:
    """(vision model name, description) for text-only chat models.

    `shots` entries carry `path` and `label`. Returns None when no image model
    is configured, or when every read failed.
    """
    try:
        backend = vision_backend_for(agent)
    except Exception:
        logger.warning("vision backend lookup failed", exc_info=True)
        return None
    if backend is None:
        return None

    raw_name = getattr(backend, "model_type", None)
    vision_model = str(getattr(raw_name, "value", raw_name) or "vision model")

    async def describe(shot: dict) -> str | None:
        try:
            with Image.open(shot["path"]) as handle:
                image = handle.convert("RGB")
        except (OSError, ValueError) as exc:
            logger.warning("cannot open %s: %s", shot["path"], exc)
            return None
        message = BaseMessage.make_user_message(
            role_name="User", content=prompt, image_list=[image]
        )
        extra = {}
        step_timeout = getattr(agent, "step_timeout", None)
        if step_timeout:
            extra["step_timeout"] = step_timeout
        try:
            vision_agent = ChatAgent(
                system_message=(
                    "You are a careful visual assistant. Describe only what "
                    "is actually visible in the image."
                ),
                model=backend,
                tools=[],
                **extra,
            )
            response = await vision_agent.astep(message)
        except Exception:
            logger.warning("vision read of %s failed", shot["path"], exc_info=True)
            return None
        msg = getattr(response, "msg", None)
        if msg is not None and getattr(msg, "content", None):
            return str(msg.content).strip()
        msgs = getattr(response, "msgs", None)
        if msgs and getattr(msgs[0], "content", None):
            return str(msgs[0].content).strip()
        return None

    selected = shots[:limit]
    parts = await asyncio.gather(*(describe(shot) for shot in selected))
    described = [
        f"- {shot.get('label') or Path(shot['path']).name}: {text}"
        for shot, text in zip(selected, parts)
        if text
    ]
    return vision_model, "\n".join(described)


def image_size(path: Path) -> tuple[int, int] | None:
    """Pixel size of a saved shot, or None when the file is not an image."""
    try:
        with Image.open(path) as handle:
            return handle.size
    except (OSError, ValueError):
        return None
