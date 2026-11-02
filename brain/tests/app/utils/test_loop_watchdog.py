# Copyright 2026 Simon Ugorji. All Rights Reserved.
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

import asyncio
import threading
import time

import pytest

from app.utils.loop_watchdog import (
    LoopWatchdog,
    start_loop_watchdog,
    stop_loop_watchdog,
    watchdog_snapshot,
)


@pytest.mark.unit
def test_watchdog_reports_no_stall_on_an_idle_loop():
    async def scenario():
        watchdog = LoopWatchdog(
            loop=asyncio.get_running_loop(),
            interval=0.02,
            stall_seconds=0.5,
            loop_thread_id=threading.get_ident(),
        )
        watchdog.start()
        await asyncio.sleep(0.2)
        watchdog.stop()
        return watchdog

    watchdog = asyncio.run(scenario())
    assert watchdog.stalls == []


@pytest.mark.unit
def test_watchdog_records_a_blocked_loop_with_the_blocking_stack():
    """The point of the watchdog: name the sync call that froze /health."""

    def blocking_call():
        time.sleep(0.5)

    async def scenario():
        watchdog = LoopWatchdog(
            loop=asyncio.get_running_loop(),
            interval=0.02,
            stall_seconds=0.15,
            loop_thread_id=threading.get_ident(),
        )
        watchdog.start()
        await asyncio.sleep(0.05)
        blocking_call()
        await asyncio.sleep(0.1)
        watchdog.stop()
        return watchdog

    watchdog = asyncio.run(scenario())
    assert len(watchdog.stalls) >= 1
    #a slow start can produce an earlier record, so look at all of them
    assert any("blocking_call" in stall.stack for stall in watchdog.stalls)
    assert any(stall.lag_seconds >= 0.15 for stall in watchdog.stalls)
    assert "LOOP THREAD" in watchdog.stalls[-1].stack
    assert watchdog.max_lag_seconds > 0.15


@pytest.mark.unit
def test_start_loop_watchdog_respects_the_disable_switch(monkeypatch):
    stop_loop_watchdog()
    monkeypatch.setenv("UNDISCLOSED_LOOP_WATCHDOG", "0")

    async def scenario():
        return start_loop_watchdog(asyncio.get_running_loop())

    assert asyncio.run(scenario()) is None
    assert "loop_stalls" not in watchdog_snapshot()
