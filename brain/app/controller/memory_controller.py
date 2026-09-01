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

"""Endpoints for the semantic (long-term) memory settings screen: how many
facts are stored, and a way to clear them. Scoped to the user when email/
user_id is provided (matching how facts are stored/recalled)."""

import logging

from fastapi import APIRouter, Query

from app.memory import semantic_store
from app.memory.paths import canonical_user_id

router = APIRouter()
memory_logger = logging.getLogger("memory_controller")


def _user_key(email: str | None, user_id: str | None) -> str | None:
    if not email and not user_id:
        return None
    try:
        return canonical_user_id(user_id, email=email)
    except ValueError:
        return None


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
