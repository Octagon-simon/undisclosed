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

"""External lifecycle notifications -- backward-compatible hook shim.

Historically this module was the whole beckon integration (see
documents/github/beckon README + EXTENDING.md): one user-configured command
(EIGENT_NOTIFY_COMMAND), run with a JSON payload on stdin whenever the agent
genuinely needs a human or a task finishes.

The mechanism now lives in :mod:`app.hooks`, which adds typed events,
per-event routing (EIGENT_HOOKS), fan-out to multiple commands, and an
overridable timeout. This module remains so existing imports
(`fire_notify`, ``EIGENT_NOTIFY_COMMAND`` setups) behave exactly as before:
with no EIGENT_HOOKS configured, fire_notify runs EIGENT_NOTIFY_COMMAND for
every event, byte-for-byte the same stdin contract as always.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("notify")

# Kept for backward compatibility with anything importing this constant.
# The live value is app.hooks.dispatcher.DEFAULT_HOOK_TIMEOUT_SECONDS,
# overridable via EIGENT_HOOK_TIMEOUT_MS.
NOTIFY_TIMEOUT_SECONDS = 2.0


async def fire_notify(event: str, data: dict[str, Any]) -> None:
    """Run configured hook commands (if any) with a JSON payload on stdin.

    Delegates to :func:`app.hooks.dispatcher.fire_hook`. Never raises -- a
    missing, broken, or slow hook must never affect the actual task. Callers
    should schedule this (asyncio.create_task or the thread-safe equivalent)
    rather than awaiting it inline, so a slow hook can't add latency to
    agent execution.
    """
    from app.hooks.dispatcher import fire_hook

    await fire_hook(event, **data)
