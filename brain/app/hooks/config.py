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

"""Hook configuration resolution.

Two layers, both optional:

1. ``EIGENT_HOOKS`` -- a JSON object mapping event names (or ``"*"``) to
   either a single command string or a list of command strings. Run through
   the shell, so entries may include their own arguments, exactly like
   ``EIGENT_NOTIFY_COMMAND`` always has:

       EIGENT_HOOKS='{"permission_requested": "node /path/beckoned-eigent-hook.js",
                      "*": "logger -t eigent-hook"}'

2. ``EIGENT_NOTIFY_COMMAND`` -- the original env var from the beckon patch.
   Kept firing for every event so existing setups (e.g. an installed
   beckoned daemon) keep working unchanged when EIGENT_HOOKS is added.

Sources combine additively -- like Claude Code's hooks, where every
registered handler for an event runs -- never override each other:

    commands(event) = EIGENT_HOOKS[event]      (if present, even if empty)
                    + EIGENT_HOOKS["*"]        (wildcard entries)
                    + EIGENT_NOTIFY_COMMAND    (unless suppressed)

An explicit empty list in EIGENT_HOOKS is the one kill switch: it
suppresses the wildcard and the legacy command for that event. This is how
an event is opted out without touching the legacy configuration.
"""

from __future__ import annotations

import json
import logging
import os

from app.hooks.events import HookEvent, event_name

logger = logging.getLogger("hooks.config")

WILDCARD = "*"


def parse_hooks_env(raw: str | None) -> dict[str, list[str]]:
    """Parse the EIGENT_HOOKS JSON document.

    Returns {} when unset or unparsable (a broken config must never take the
    backend down; a warning is logged instead).
    """
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("EIGENT_HOOKS is not valid JSON; hooks config ignored")
        return {}
    if not isinstance(parsed, dict):
        logger.warning(
            "EIGENT_HOOKS must be a JSON object mapping event names to "
            "commands; got %s",
            type(parsed).__name__,
        )
        return {}

    table: dict[str, list[str]] = {}
    for key, value in parsed.items():
        name = str(key)
        if name != WILDCARD:
            try:
                HookEvent(name)
            except ValueError:
                logger.warning(
                    "EIGENT_HOOKS references unknown hook event '%s'; "
                    "entry ignored (known events: %s)",
                    name,
                    ", ".join(e.value for e in HookEvent),
                )
                continue
        if isinstance(value, str):
            table[name] = [value]
            continue
        if isinstance(value, (list, tuple)):
            # An explicitly empty list is meaningful: it suppresses this
            # event's hooks entirely, including wildcard and legacy-command
            # fallbacks. Keep the key with an empty list.
            table[name] = [item for item in value if isinstance(item, str)]
            continue
        logger.warning(
            "EIGENT_HOOKS entry for '%s' must be a command string or a "
            "list of command strings; got %s",
            name,
            type(value).__name__,
        )
    return table


def resolve_commands_for_event(event: HookEvent | str) -> list[str]:
    """Commands to run for an event: specific, wildcard, and legacy combined.

    Sources are additive (see module docstring); duplicates are removed
    preserving order. Never raises; no configuration yields [] (a no-op),
    which is what makes firing hooks safe on hot paths. An explicit empty
    list for the event suppresses the wildcard and legacy contributions.
    """
    name = event_name(event)
    table = parse_hooks_env(os.environ.get("EIGENT_HOOKS"))

    specific = table.get(name)
    wildcard = table.get(WILDCARD)

    commands: list[str] = []
    if specific:
        commands.extend(specific)
    if wildcard:
        commands.extend(wildcard)

    # Legacy command keeps firing for every event unless the event is
    # explicitly suppressed with an empty list in EIGENT_HOOKS.
    legacy = os.environ.get("EIGENT_NOTIFY_COMMAND", "").strip()
    if legacy and specific != []:
        commands.append(legacy)

    # De-duplicate while preserving order (a repeated command would run its
    # side effects twice).
    seen: set[str] = set()
    unique: list[str] = []
    for command in commands:
        if command not in seen:
            seen.add(command)
            unique.append(command)
    return unique


def is_configured() -> bool:
    """True when any hook source is configured at all."""
    if os.environ.get("EIGENT_NOTIFY_COMMAND", "").strip():
        return True
    return bool(parse_hooks_env(os.environ.get("EIGENT_HOOKS")))
