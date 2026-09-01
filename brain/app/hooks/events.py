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

"""Hook event taxonomy.

The payload shape on stdin stays byte-compatible with what beckon's
``eigent-hook`` adapter already parses (see documents/github/beckon,
``src/adapters/eigent-hook.ts``): a flat JSON object starting with
``{"event": <name>, "timestamp": <epoch-seconds-float>}``, followed by flat,
string-or-number fields. New event kinds and new optional fields are safe to
add -- unknown events are silently ignored downstream -- but field values must
stay JSON scalars so existing adapters never see nested structures they don't
expect.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any


class HookEvent(str, Enum):
    """Lifecycle events that can trigger user-configured hook commands.

    Grouped by subsystem. Permission events are part of the taxonomy from day
    one so the governance layer (ApprovalManager) can fire them with one call
    as soon as it lands; nothing else needs to change when it does.
    """

    # --- Task lifecycle ---------------------------------------------------
    task_started = "task_started"  # a turn begins executing
    task_end = "task_end"  # turn/task completed (existing beckon event)
    task_failed = "task_failed"  # turn raised before producing a result
    task_cancelled = "task_cancelled"  # stopped/skipped by the user

    # --- Human attention (existing beckon event) ---------------------------
    human_input_requested = "human_input_requested"

    # --- Permission / execution-governance ---------------------------------
    permission_requested = "permission_requested"
    permission_approved = "permission_approved"
    permission_denied = "permission_denied"
    permission_timeout = "permission_timeout"  # auto-deny after timeout

    # --- Session ------------------------------------------------------------
    session_paused = "session_paused"
    session_resumed = "session_resumed"


def build_payload(
    event: HookEvent | str, data: dict[str, Any]
) -> dict[str, Any]:
    """Merge event name + data into the canonical stdin payload.

    Same field set as notify.py has always emitted (``event``, flat extras,
    ``timestamp``); JSON objects are parsed by key, so key order is free for
    consumers like beckon's adapter. ``data`` wins over accidental collisions
    except for ``event``, which is always canonical.
    """
    if isinstance(event, HookEvent):
        event_name: str = event.value
    else:
        event_name = str(event)
    payload: dict[str, Any] = {"event": event_name, **data}
    # Canonical fields always win, whatever data carried.
    payload["event"] = event_name
    payload.setdefault("timestamp", time.time())
    return payload


def event_name(event: HookEvent | str) -> str:
    """Canonical string name for an event."""
    return event.value if isinstance(event, HookEvent) else str(event)
