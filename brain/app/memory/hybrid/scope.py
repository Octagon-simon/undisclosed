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

"""Memory scope: the physical home of user-level memory + the promotion rules.

``memory-cross-session-feature.md`` §2/§6/§23 split durable memory into three
scopes -- ``global`` (user), ``project``, and ``conversation``. This module owns
the two pieces the rest of the layer needs to honour that split:

* :class:`GlobalMemoryStore` -- a :class:`~app.memory.hybrid.storage.HybridStore`
  whose sidecars live at the *user* root instead of a project dir. A global
  record has to be recoverable from any thread, so it cannot live under a single
  project; reusing the store means global memory gets the same record shape,
  versioning, supersession, and ``apply_ops`` mutation gate as project memory.

* :func:`infer_scope` / :func:`resolve_op_scope` -- the deterministic fallback for
  the §23 promotion hierarchy. The extraction layer normally classifies scope
  itself (the model sees "I prefer TypeScript" and proposes a global op); when it
  does not, this decides whether a proposal is user-level, project-level, or
  thread-only so a temporary choice never becomes a permanent global fact.

* :func:`iter_user_projects` -- enumerates a user's other projects so retrieval
  can widen from the current thread to the rest of the user's sessions (§11-12).
"""

from __future__ import annotations

import re
from pathlib import Path

from app.memory.hybrid.schema import (
    MEMORY_SCOPES,
    SCOPE_CONVERSATION,
    SCOPE_GLOBAL,
    SCOPE_PROJECT,
    MemoryOp,
)
from app.memory.hybrid.storage import HybridStore

# Durable, user-level signals: a stable preference/convention the user states
# about themselves rather than about one project (§2 "global memory", §23).
_GLOBAL_PATTERNS = (
    r"\bi (?:always|usually|generally|typically|normally)\b",
    r"\bi (?:prefer|like to|tend to|want)\b",
    r"\bmy (?:preference|preferences|style|convention|conventions|rule|rules)\b",
    r"\bfrom now on\b",
    r"\bgoing forward\b",
    r"\bacross (?:all|every|any) (?:projects?|threads?|conversations?)\b",
)

# Thread-only signals: an explicitly temporary / one-off choice that must not
# leak into other sessions (§23 "for this one prototype, use SQLite").
_CONVERSATION_PATTERNS = (
    r"\bjust this once\b",
    r"\bone[- ]?off\b",
    r"\btemporarily\b",
    r"\bfor now\b",
    r"\bin this (?:chat|thread|conversation)\b",
    r"\bfor this (?:prototype|demo|test|experiment|exercise|draft)\b",
)

_GLOBAL_RE = re.compile("|".join(_GLOBAL_PATTERNS))
_CONVERSATION_RE = re.compile("|".join(_CONVERSATION_PATTERNS))


class GlobalMemoryStore(HybridStore):
    """A :class:`HybridStore` rooted at the user dir (holds ``global`` memory).

    The only behavioural change is :meth:`_dir`: sidecars land at
    ``<user>/memories.json`` rather than ``<user>/spaces/<s>/projects/<p>/``, so
    a user-level record is reachable from every conversation. Episodes/working
    memory would also resolve there, but global memory only ever writes the
    memories sidecar, so that is harmless.
    """

    def _dir(self, user_key: str, space_id: str, project_id: str) -> Path:
        return self.base.user_path(user_key)


def infer_scope(op: MemoryOp) -> str:
    """Best-effort deterministic scope for one proposal (§23).

    Conversation-scoped phrases win over global ones: an explicit "just this
    once" must beat a generic "I prefer", otherwise a one-off choice would be
    promoted to a permanent fact. ``preference`` type defaults to global -- a
    stated preference is the canonical user-level memory -- and everything else
    defaults to project, which is the safe (non-leaking) home for a decision or
    constraint that names no other scope.
    """

    text = f"{op.key} {op.value}".lower()
    if _CONVERSATION_RE.search(text):
        return SCOPE_CONVERSATION
    if _GLOBAL_RE.search(text):
        return SCOPE_GLOBAL
    if (op.type or "").lower() == "preference":
        return SCOPE_GLOBAL
    return SCOPE_PROJECT


def resolve_op_scope(
    op: MemoryOp,
    *,
    user_key: str,
    project_id: str,
    conversation_id: str,
) -> tuple[str, str, str]:
    """Return ``(scope_type, scope_id, user_id)`` for one proposal.

    An explicit ``op.scope_type`` (set by the extraction LLM) is honoured when it
    is one of the known scopes; otherwise :func:`infer_scope` decides. The
    ``scope_id`` is filled from the scope: the user key for global, the project
    id for project, the conversation id for conversation. Only global records
    carry a ``user_id`` -- it names the owning user for a record that is not
    anchored to any single project.
    """

    scope_type = (op.scope_type or "").strip().lower()
    if scope_type not in MEMORY_SCOPES:
        scope_type = infer_scope(op)

    if scope_type == SCOPE_GLOBAL:
        return scope_type, user_key, user_key
    if scope_type == SCOPE_CONVERSATION:
        return scope_type, conversation_id, ""
    return SCOPE_PROJECT, project_id, ""


def partition_by_scope(
    ops: list[MemoryOp],
    *,
    user_key: str,
    project_id: str,
    conversation_id: str,
) -> dict[str, list[MemoryOp]]:
    """Group proposals by their resolved scope so each batch can be written to
    the store that owns that scope. Targeted ops (SUPERSEDE/DELETE/MERGE) always
    stay with the project store -- they address an existing project record by id
    and nothing else can resolve that id."""

    buckets: dict[str, list[MemoryOp]] = {
        SCOPE_GLOBAL: [],
        SCOPE_PROJECT: [],
        SCOPE_CONVERSATION: [],
    }
    for op in ops:
        name = (op.op or "").upper()
        if name != "UPSERT":
            buckets[SCOPE_PROJECT].append(op)
            continue
        scope_type, _scope_id, _user_id = resolve_op_scope(
            op,
            user_key=user_key,
            project_id=project_id,
            conversation_id=conversation_id,
        )
        buckets[scope_type].append(op)
    return buckets


def iter_user_projects(store: HybridStore, user_key: str) -> list[tuple[str, str]]:
    """Every ``(space_id, project_id)`` under a user root (§11-12).

    Cross-session retrieval needs to look past the current thread. This walks the
    on-disk layout (``<user>/spaces/<space>/projects/<project>``) rather than a
    registry, so it works after a restart with nothing but the durable tree.
    Missing/unreadable roots yield ``[]`` -- retrieval degrades to the current
    project instead of failing.
    """

    # Accept either a HybridStore (unwraps to its LocalMemoryStore) or a
    # LocalMemoryStore directly, so callers do not need to know which they hold.
    base = getattr(store, "base", store)
    root = base.user_path(user_key) / "spaces"
    out: list[tuple[str, str]] = []
    try:
        spaces = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return out
    for space in spaces:
        projects_dir = space / "projects"
        try:
            projects = sorted(p for p in projects_dir.iterdir() if p.is_dir())
        except OSError:
            continue
        out.extend((space.name, project.name) for project in projects)
    return out
