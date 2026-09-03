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

"""Beckon-style lifecycle hooks for Undisclosed's backend.

Generalizes the original single-command ``EIGENT_NOTIFY_COMMAND`` patch into
a hook system with typed events, per-event command routing, fan-out to
multiple commands, and strict failure isolation. Wire format stays
compatible with beckon's ``eigent-hook`` adapter (flat JSON on stdin).
"""

from app.hooks.config import parse_hooks_env, resolve_commands_for_event
from app.hooks.dispatcher import (
    dispatch_payload,
    emit_event_thread_safe,
    fire_hook,
    get_hook_timeout,
    run_hook_command,
)
from app.hooks.emitters import (
    emit_permission_requested,
    emit_permission_resolved,
    emit_session_paused,
    emit_session_resumed,
    emit_task_cancelled,
    emit_task_completed,
    emit_task_failed,
    emit_task_started,
)
from app.hooks.events import HookEvent, build_payload, event_name

__all__ = [
    "HookEvent",
    "build_payload",
    "dispatch_payload",
    "emit_event_thread_safe",
    "emit_permission_requested",
    "emit_permission_resolved",
    "emit_session_paused",
    "emit_session_resumed",
    "emit_task_cancelled",
    "emit_task_completed",
    "emit_task_failed",
    "emit_task_started",
    "event_name",
    "fire_hook",
    "get_hook_timeout",
    "parse_hooks_env",
    "resolve_commands_for_event",
    "run_hook_command",
]
