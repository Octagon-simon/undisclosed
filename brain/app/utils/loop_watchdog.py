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

"""Event-loop stall detector.

A sync call on the loop thread (a blocking subprocess, a large JSON build, a
tool doing disk I/O inline) freezes every coroutine, including the ``/health``
handler the desktop app polls. The app then reports "brain offline" even though
the process is alive, and the log shows nothing because nothing ran.

The watchdog lives on a DAEMON THREAD, so it keeps running while the loop is
blocked. It queues a marker callback onto the loop every interval; if the
marker does not run within ``stall_seconds`` the loop is stalled and we dump
every thread's stack with ``sys._current_frames()``. The loop thread's top
frames name the blocking call.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("loop_watchdog")

DEFAULT_INTERVAL_SECONDS = 0.5
DEFAULT_STALL_SECONDS = 1.0
#a stall only needs a couple of stacks; more just fills the log
MAX_RECORDED_STALLS = 10
MAX_STACK_CHARS = 6000
#innermost frames are the interesting ones; a deep framework stack buries them
STACK_FRAMES_PER_THREAD = 15


@dataclass
class StallRecord:
    at: float
    lag_seconds: float
    stack: str


@dataclass
class LoopWatchdog:
    """Watch one event loop from a background thread and report stalls."""

    loop: Any
    interval: float = DEFAULT_INTERVAL_SECONDS
    stall_seconds: float = DEFAULT_STALL_SECONDS
    loop_thread_id: int | None = None
    _thread: threading.Thread | None = None
    _stop: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    max_lag_seconds: float = 0.0
    stalls: list[StallRecord] = field(default_factory=list)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="loop-watchdog", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            last = self.stalls[-1] if self.stalls else None
            return {
                "loop_max_lag_ms": round(self.max_lag_seconds * 1000),
                "loop_stalls": len(self.stalls),
                "loop_last_stall_at": last.at if last else None,
            }

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            fired = threading.Event()
            sent = time.monotonic()
            try:
                self.loop.call_soon_threadsafe(fired.set)
            except RuntimeError:
                return  #loop closed
            if fired.wait(self.stall_seconds):
                lag = time.monotonic() - sent
                with self._lock:
                    if lag > self.max_lag_seconds:
                        self.max_lag_seconds = lag
                continue
            self._record(time.monotonic() - sent)
            #wait for the loop to come back so max_lag is the real stall
            if fired.wait():
                with self._lock:
                    self.max_lag_seconds = max(
                        self.max_lag_seconds, time.monotonic() - sent
                    )

    def _record(self, lag: float) -> None:
        stack = _format_thread_stacks(self.loop_thread_id)
        record = StallRecord(at=time.time(), lag_seconds=lag, stack=stack)
        with self._lock:
            self.max_lag_seconds = max(self.max_lag_seconds, lag)
            self.stalls.append(record)
            del self.stalls[:-MAX_RECORDED_STALLS]
        logger.warning(
            "[LOOP STALL] event loop blocked for %.2fs; offending stack:\n%s",
            lag,
            stack,
        )


def _format_thread_stacks(loop_thread_id: int | None = None) -> str:
    """Dump every thread's stack. Readable while the loop thread is blocked."""
    frames = sys._current_frames()
    names = {t.ident: t.name for t in threading.enumerate()}
    own = threading.get_ident()
    order = [loop_thread_id] if loop_thread_id else []
    order += [
        ident for ident in frames if ident not in order and ident != own
    ]
    chunks: list[str] = []
    for ident in order:
        frame = frames.get(ident)
        if frame is None:
            continue
        label = "LOOP THREAD" if ident == loop_thread_id else "thread"
        name = names.get(ident, str(ident))
        stack = traceback.format_stack(frame)[-STACK_FRAMES_PER_THREAD:]
        chunks.append(f"--- {label} {name} ---\n{''.join(stack)}")
    text = "\n".join(chunks)
    return text[:MAX_STACK_CHARS]


_WATCHDOG: LoopWatchdog | None = None


def start_loop_watchdog(loop: Any) -> LoopWatchdog | None:
    """Start the process-wide watchdog. No-op when disabled by env."""
    global _WATCHDOG
    if _WATCHDOG is not None:
        return _WATCHDOG
    raw = os.environ.get("UNDISCLOSED_LOOP_WATCHDOG", "1").strip().lower()
    if raw in {"0", "false", "off", "no"}:
        return None
    try:
        watchdog = LoopWatchdog(
            loop=loop,
            stall_seconds=float(
                os.environ.get("UNDISCLOSED_LOOP_STALL_MS", "1000")
            )
            / 1000.0,
            loop_thread_id=threading.get_ident(),
        )
        watchdog.start()
        _WATCHDOG = watchdog
        return watchdog
    except Exception:  # noqa: BLE001 - never block boot
        logger.warning("loop watchdog failed to start", exc_info=True)
        return None


def stop_loop_watchdog() -> None:
    global _WATCHDOG
    if _WATCHDOG is not None:
        _WATCHDOG.stop()
        _WATCHDOG = None


def watchdog_snapshot() -> dict[str, Any]:
    snapshot = _WATCHDOG.snapshot() if _WATCHDOG is not None else {}
    snapshot["loop_last_stall_stack"] = (
        _WATCHDOG.stalls[-1].stack if _WATCHDOG and _WATCHDOG.stalls else ""
    )
    return snapshot
