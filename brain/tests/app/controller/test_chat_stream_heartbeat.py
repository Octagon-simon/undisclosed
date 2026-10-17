# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
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

"""Regression tests for the live chat SSE wrapper.

Covers the "agent stopped responding after a long idle chat" fix:
  1. an idle-but-healthy stream emits `sync` heartbeats instead of being torn
     down by the one-hour no-data timeout, and
  2. a real idle timeout preserves a completed task lock that still holds
     conversation context (so a later re-attach keeps the session), while an
     empty lock is still cleaned up.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.controller.chat_controller import timeout_stream_wrapper
from app.model.chat import Status

pytestmark = pytest.mark.unit


def _parse_sse(line: str) -> tuple[str, object]:
    assert line.startswith("data: "), line
    try:
        payload = json.loads(line[len("data: ") :].strip())
    except json.JSONDecodeError:
        return "raw", line
    return payload.get("step", ""), payload.get("data")


@pytest.mark.asyncio
async def test_idle_stream_emits_heartbeats_without_timing_out():
    """A silent generator must not kill the stream; heartbeats keep it warm."""

    async def gen():
        await asyncio.sleep(0.12)
        yield "data: final\n\n"

    chunks: list[str] = []
    async for chunk in timeout_stream_wrapper(
        gen(),
        timeout_seconds=30,
        heartbeat_seconds=0.02,
        task_lock=SimpleNamespace(
            id="p1", status=Status.done, conversation_history=[{"x": 1}]
        ),
    ):
        chunks.append(chunk)

    steps = [_parse_sse(c)[0] for c in chunks]
    assert steps.count("sync") >= 1, chunks
    assert "error" not in steps
    assert chunks[-1] == "data: final\n\n"


@pytest.mark.asyncio
async def test_idle_timeout_preserves_lock_with_history():
    """On true timeout, keep a completed lock that still has context."""

    async def gen():
        await asyncio.sleep(10)
        yield "data: never\n\n"  # pragma: no cover - cancelled first

    lock = SimpleNamespace(
        id="p1",
        status=Status.done,
        conversation_history=[{"role": "user", "content": "hi"}],
    )

    with patch(
        "app.controller.chat_controller._cleanup_task_lock_safe",
        new=AsyncMock(return_value=True),
    ) as cleanup:
        chunks: list[str] = []
        async for chunk in timeout_stream_wrapper(
            gen(),
            timeout_seconds=0.05,
            heartbeat_seconds=0.01,
            task_lock=lock,
        ):
            chunks.append(chunk)

    steps = [_parse_sse(c)[0] for c in chunks]
    assert "error" in steps, chunks
    cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_idle_timeout_cleans_up_lock_without_history():
    """A well-timed-out, empty session lock is still cleaned up."""

    async def gen():
        await asyncio.sleep(10)
        yield "data: never\n\n"  # pragma: no cover - cancelled first

    lock = SimpleNamespace(
        id="p1", status=Status.done, conversation_history=[]
    )

    with patch(
        "app.controller.chat_controller._cleanup_task_lock_safe",
        new=AsyncMock(return_value=True),
    ) as cleanup:
        async for _chunk in timeout_stream_wrapper(
            gen(),
            timeout_seconds=0.05,
            heartbeat_seconds=0.01,
            task_lock=lock,
        ):
            pass

    cleanup.assert_awaited_once()
    assert cleanup.await_args.args[1] == "TIMEOUT"
