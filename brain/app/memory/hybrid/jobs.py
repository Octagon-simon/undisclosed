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

"""Durable, retryable memory jobs (§20, §21, §33).

Post-run extraction used to be a fire-and-forget background thread: if the
process died mid-task the work was simply gone. This module makes it durable.
A job is a small record in ``<user>/memory_jobs.json`` that a worker *claims*
before doing the work and marks ``completed``/``failed`` afterwards, so:

* a crash leaves the job ``processing`` and :meth:`MemoryJobStore.recover_stale`
  returns it to the pool on the next start-up (§20 "pending async jobs should be
  recoverable");
* a retry cannot double-write, because :meth:`enqueue` refuses to create a second
  job for an ``idempotency_key`` that already exists (§33);
* a flaky extraction is re-attempted up to ``max_attempts`` before it is marked
  ``failed`` (§32 "retry -> deterministic fallback").

The store is a single JSON file at the user root (alongside the project registry
and global memory), written through the shared atomic read-modify-write helper,
so a job transition can never be torn by a concurrent writer in the same Brain
process.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.memory.hybrid.schema import SCHEMA_VERSION, MemoryJob
from app.memory.local_store import (
    LocalMemoryStore,
    update_json_file,
)

logger = logging.getLogger("memory.hybrid.jobs")

_JOBS = "memory_jobs.json"

DEFAULT_MAX_ATTEMPTS = 3
# A ``processing`` job older than this is assumed abandoned by a crashed worker
# (§20). Generous: extraction can involve a model call.
STALE_PROCESSING_SECONDS = 900
# Bound on the retain-log so the file cannot grow without limit. Terminal jobs
# are dropped oldest-first; open (pending/processing/retrying) jobs are never
# pruned, because losing one would lose work.
_KEEP_JOBS = 500


def extraction_key(
    conversation_id: str,
    run_id: str,
    *,
    schema_version: int = SCHEMA_VERSION,
) -> str:
    """Stable idempotency key for one extraction job (§21, §33).

    Shape matches the spec example: same conversation + same source range +
    same extractor version resolves to the same logical job, so a retry can
    never produce a second episode or duplicate memory.
    """

    return (
        f"memory-extraction:{conversation_id}:{run_id}:v{schema_version}"
    )


def _new_id() -> str:
    return "job_" + uuid.uuid4().hex[:16]


def _parse_ts(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _plus_seconds(now: str, seconds: int) -> str:
    base = _parse_ts(now)
    if base is None:
        return ""
    return (base + timedelta(seconds=seconds)).isoformat()


def _load(payload: Any) -> list[MemoryJob]:
    rows = payload.get("jobs") if isinstance(payload, dict) else None
    out: list[MemoryJob] = []
    for row in rows if isinstance(rows, list) else []:
        job = MemoryJob.from_dict(row)
        if job is not None:
            out.append(job)
    return out


def _dump(jobs: list[MemoryJob]) -> dict[str, Any]:
    return {"jobs": [job.to_dict() for job in jobs]}


def _pruned(jobs: list[MemoryJob], keep: int = _KEEP_JOBS) -> list[MemoryJob]:
    """Drop the oldest terminal jobs so the file stays bounded."""

    if len(jobs) <= keep:
        return jobs
    overflow = len(jobs) - keep
    ordered = sorted(jobs, key=lambda job: job.created_at or "")
    drop: set[str] = set()
    for job in ordered:
        if overflow <= 0:
            break
        if job.is_terminal():
            drop.add(job.id)
            overflow -= 1
    return [job for job in jobs if job.id not in drop]


class MemoryJobStore:
    """Durable job table for one user, kept at ``<user>/memory_jobs.json``."""

    def __init__(self, store: LocalMemoryStore) -> None:
        self._store = store

    @property
    def base(self) -> LocalMemoryStore:
        return self._store

    def _path(self, user_key: str) -> Path:
        return self._store.user_path(user_key) / _JOBS

    # ----- Reads -----

    def read_jobs(self, user_key: str) -> list[MemoryJob]:
        from app.memory.local_store import read_json_file

        return _load(read_json_file(self._path(user_key)))

    def get(self, user_key: str, job_id: str) -> MemoryJob | None:
        for job in self.read_jobs(user_key):
            if job.id == job_id:
                return job
        return None

    def find_by_key(self, user_key: str, idempotency_key: str) -> MemoryJob | None:
        for job in self.read_jobs(user_key):
            if job.idempotency_key == idempotency_key:
                return job
        return None

    def pending_count(self, user_key: str) -> int:
        return sum(1 for job in self.read_jobs(user_key) if job.is_claimable())

    # ----- Writes -----

    def enqueue(
        self,
        *,
        idempotency_key: str,
        user_key: str,
        space_id: str = "",
        project_id: str = "",
        conversation_id: str = "",
        run_id: str = "",
        run_state: str = "done",
        now: str = "",
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> MemoryJob | None:
        """Create a job, or return the existing one for this key (§33).

        Enqueue is idempotent on ``idempotency_key``: if any job already carries
        the key, that record is returned unchanged and no new work is created.
        Returns ``None`` only when no key is supplied.
        """

        if not idempotency_key:
            return None
        found: MemoryJob | None = None

        def _mutate(payload: Any) -> dict[str, Any]:
            nonlocal found
            jobs = _load(payload)
            existing = next(
                (
                    job
                    for job in jobs
                    if job.idempotency_key == idempotency_key
                ),
                None,
            )
            if existing is not None:
                found = existing
                return _dump(jobs)
            job = MemoryJob(
                id=_new_id(),
                idempotency_key=idempotency_key,
                user_key=user_key,
                space_id=space_id,
                project_id=project_id,
                conversation_id=conversation_id,
                run_id=run_id,
                run_state=run_state,
                state="pending",
                max_attempts=max_attempts,
                created_at=now,
                updated_at=now,
            )
            jobs.append(job)
            found = job
            return _dump(_pruned(jobs))

        update_json_file(self._path(user_key), _mutate)
        return found

    def claim(
        self, user_key: str, job_id: str | None = None, *, now: str = ""
    ) -> MemoryJob | None:
        """Mark one claimable job ``processing`` and return it.

        With ``job_id`` the named job is claimed if it is claimable; without it,
        the oldest eligible job is claimed (a ``retrying`` job is eligible once
        its ``next_attempt_at`` has passed).
        """

        claimed: MemoryJob | None = None

        def _mutate(payload: Any) -> dict[str, Any]:
            nonlocal claimed
            jobs = _load(payload)
            target: MemoryJob | None = None
            if job_id:
                target = next(
                    (
                        job
                        for job in jobs
                        if job.id == job_id and job.is_claimable()
                    ),
                    None,
                )
            else:
                now_dt = _parse_ts(now)
                for job in sorted(
                    (job for job in jobs if job.is_claimable()),
                    key=lambda job: job.created_at or "",
                ):
                    due = _parse_ts(job.next_attempt_at)
                    if due is not None and now_dt is not None and due > now_dt:
                        continue
                    target = job
                    break
            if target is None:
                return _dump(jobs)
            updated = MemoryJob(
                **{
                    **target.to_dict(),
                    "state": "processing",
                    "attempts": target.attempts + 1,
                    "claimed_at": now,
                    "updated_at": now,
                    "next_attempt_at": "",
                    "last_error": "",
                }
            )
            jobs = [updated if job.id == target.id else job for job in jobs]
            claimed = updated
            return _dump(jobs)

        update_json_file(self._path(user_key), _mutate)
        return claimed

    def complete(
        self, user_key: str, job_id: str, *, now: str = ""
    ) -> MemoryJob | None:
        return self._transition(
            user_key,
            job_id,
            state="completed",
            now=now,
            fields={"last_error": ""},
        )

    def fail(
        self, user_key: str, job_id: str, *, error: str = "", now: str = ""
    ) -> MemoryJob | None:
        """Record a failure, scheduling a retry until ``max_attempts`` (§32)."""

        current = self.get(user_key, job_id)
        if current is None:
            return None
        if current.attempts >= max(1, current.max_attempts):
            return self._transition(
                user_key,
                job_id,
                state="failed",
                now=now,
                fields={"last_error": error[:500]},
            )
        # Linear backoff, capped; a retry is never immediate to avoid a hot loop.
        delay = min(300, 15 * max(1, current.attempts))
        return self._transition(
            user_key,
            job_id,
            state="retrying",
            now=now,
            fields={
                "last_error": error[:500],
                "next_attempt_at": _plus_seconds(now, delay),
            },
        )

    def _transition(
        self,
        user_key: str,
        job_id: str,
        *,
        state: str,
        now: str,
        fields: dict[str, str],
    ) -> MemoryJob | None:
        updated: MemoryJob | None = None

        def _mutate(payload: Any) -> dict[str, Any]:
            nonlocal updated
            jobs = _load(payload)
            for index, job in enumerate(jobs):
                if job.id != job_id:
                    continue
                new = MemoryJob(
                    **{
                        **job.to_dict(),
                        **fields,
                        "state": state,
                        "updated_at": now,
                    }
                )
                jobs[index] = new
                updated = new
                break
            return _dump(jobs)

        update_json_file(self._path(user_key), _mutate)
        return updated

    def recover_stale(
        self,
        user_key: str,
        *,
        now: str = "",
        stale_after_seconds: int = STALE_PROCESSING_SECONDS,
    ) -> int:
        """Return abandoned ``processing`` jobs to the pool (§20).

        A job is stale when it has no ``claimed_at`` (a torn write) or when its
        claim is older than ``stale_after_seconds``. Returns how many were
        recovered. Never touches ``pending``/``retrying`` jobs.
        """

        recovered = 0

        def _mutate(payload: Any) -> dict[str, Any]:
            nonlocal recovered
            jobs = _load(payload)
            now_dt = _parse_ts(now)
            for index, job in enumerate(jobs):
                if job.state != "processing":
                    continue
                claimed = _parse_ts(job.claimed_at)
                if claimed is None or (
                    now_dt is not None
                    and (now_dt - claimed).total_seconds()
                    > stale_after_seconds
                ):
                    jobs[index] = MemoryJob(
                        **{
                            **job.to_dict(),
                            "state": "retrying",
                            "next_attempt_at": "",
                            "updated_at": now,
                        }
                    )
                    recovered += 1
            return _dump(jobs)

        update_json_file(self._path(user_key), _mutate)
        return recovered
