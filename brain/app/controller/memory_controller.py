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

"""Endpoints for the semantic (long-term) memory settings screen (how many
facts are stored, a way to clear them) plus the conversation HANDOFF export.

All endpoints are scoped to the user when email/user_id is provided, matching
how facts and summaries are stored/recalled."""

import logging

from fastapi import APIRouter, Query

from app.memory import rolling_summary, semantic_store
from app.memory.local_store import LocalMemoryStore
from app.memory.paths import canonical_user_id

router = APIRouter()
memory_logger = logging.getLogger("memory_controller")


def _user_key(email: str | None, user_id: str | None) -> str:
    if email or user_id:
        try:
            return canonical_user_id(user_id, email=email)
        except ValueError:
            pass
    return "user_0"


@router.get("/memory/status")
def memory_status(
    email: str | None = Query(None),
    user_id: str | None = Query(None),
) -> dict:
    """Stored-fact count for this user (or all when unscoped)."""
    key = _user_key(email, user_id)
    return {"count": semantic_store.count(key)}


@router.delete("/memory")
def memory_clear(
    email: str | None = Query(None),
    user_id: str | None = Query(None),
) -> dict:
    """Delete this user's stored facts (or all when unscoped)."""
    key = _user_key(email, user_id)
    removed = semantic_store.clear(key)
    memory_logger.info("Cleared %d semantic memory facts", removed)
    return {"removed": removed}


@router.get("/memory/handoff")
def memory_handoff(
    project_id: str = Query(...),
    space_id: str = Query("default"),
    email: str | None = Query(None),
    user_id: str | None = Query(None),
) -> dict:
    """Render a conversation HANDOFF: a structured carry-forward brief.

    A handoff seeds a NEW chat. It carries the objective, status, touched files,
    commands run, verification evidence, blockers and the next safe action from
    the current conversation in a few hundred tokens, so the user can branch
    without dragging the whole transcript (and its token cost) into the next
    model window. Read-only and best-effort: an empty/missing summary returns
    `found: false` rather than an error.
    """
    key = _user_key(email, user_id)
    if not project_id:
        return {"found": False, "markdown": "", "turn_count": 0, "sections": None}
    try:
        store = LocalMemoryStore()
        summary = rolling_summary.load(store, key, space_id, project_id)
        if summary is None or not summary.turns:
            # Check other spaces for this user if space_id defaulted or differed
            spaces_root = store.user_path(key) / "spaces"
            if spaces_root.is_dir():
                for sp_dir in spaces_root.iterdir():
                    if sp_dir.is_dir() and sp_dir.name != space_id:
                        candidate = rolling_summary.load(
                            store, key, sp_dir.name, project_id
                        )
                        if candidate and candidate.turns:
                            summary = candidate
                            break

        if summary is None or not summary.turns:
            return {"found": False, "markdown": "", "turn_count": 0, "sections": None}
        markdown = rolling_summary.render_handoff_md(summary)
        sections = rolling_summary.handoff_sections(summary)
    except Exception:  # noqa: BLE001 — best-effort read, never 500 the UI
        memory_logger.debug("handoff render failed", exc_info=True)
        return {"found": False, "markdown": "", "turn_count": 0, "sections": None}
    return {
        "found": bool(markdown.strip()),
        "markdown": markdown,
        "turn_count": summary.turn_count,
        "sections": sections,
    }
