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

"""Durable job table + restart / retry behaviour (§20, §21, §33)."""

from __future__ import annotations

from app.memory.events import ConversationEvent
from app.memory.hybrid import engine, jobs
from app.memory.hybrid.jobs import MemoryJobStore, extraction_key

IDS = {
    "user_key": "user_42",
    "space_id": "space_test",
    "project_id": "project_test",
    "conversation_id": "project_test",
}


def _seed_turn(hybrid, ids, text="we'll use PostgreSQL for the database"):
    hybrid.base.append_conversation(
        ids["user_key"],
        ids["space_id"],
        ids["project_id"],
        ConversationEvent(
            event_id="evt_1",
            run_id="run1",
            timestamp="t",
            role="user",
            content=text,
            source="chat",
            visibility="context",
            hash="sha256:x",
        ),
    )


class TestJobStore:
    def test_enqueue_is_idempotent_on_key(self, store):
        js = MemoryJobStore(store)
        first = js.enqueue(idempotency_key="k1", user_key="u", now="2026-01-01T00:00:00+00:00")
        second = js.enqueue(idempotency_key="k1", user_key="u", now="2026-01-01T00:01:00+00:00")
        assert first is not None and second is not None
        assert first.id == second.id
        assert len(js.read_jobs("u")) == 1

    def test_jobs_are_durable_across_store_instances(self, store):
        MemoryJobStore(store).enqueue(
            idempotency_key="k1", user_key="u", now="t1"
        )
        # A "restart": brand new store object over the same tree.
        assert len(MemoryJobStore(store).read_jobs("u")) == 1

    def test_claim_marks_processing_and_increments_attempts(self, store):
        js = MemoryJobStore(store)
        js.enqueue(idempotency_key="k1", user_key="u", now="t1")
        claimed = js.claim("u", now="t2")
        assert claimed is not None
        assert claimed.state == "processing"
        assert claimed.attempts == 1
        # A processing job is not claimable again.
        assert js.claim("u", now="t3") is None

    def test_claim_by_id_only_when_claimable(self, store):
        js = MemoryJobStore(store)
        job = js.enqueue(idempotency_key="k1", user_key="u", now="t1")
        assert js.claim("u", job.id, now="t2") is not None
        assert js.claim("u", job.id, now="t3") is None

    def test_complete_is_terminal(self, store):
        js = MemoryJobStore(store)
        job = js.enqueue(idempotency_key="k1", user_key="u", now="t1")
        js.claim("u", job.id, now="t2")
        done = js.complete("u", job.id, now="t3")
        assert done is not None and done.state == "completed"
        assert done.is_terminal()
        assert js.pending_count("u") == 0

    def test_fail_retries_then_gives_up(self, store):
        js = MemoryJobStore(store)
        job = js.enqueue(
            idempotency_key="k1", user_key="u", now="2026-01-01T00:00:00+00:00",
            max_attempts=2,
        )
        js.claim("u", job.id, now="2026-01-01T00:00:00+00:00")
        first = js.fail("u", job.id, error="boom", now="2026-01-01T00:00:00+00:00")
        assert first is not None
        assert first.state == "retrying"
        assert first.next_attempt_at  # a backoff was scheduled
        assert first.last_error == "boom"
        js.claim("u", job.id, now="2026-01-01T00:05:00+00:00")
        second = js.fail("u", job.id, error="boom2", now="2026-01-01T00:05:00+00:00")
        assert second is not None and second.state == "failed"
        assert second.is_terminal()

    def test_retrying_job_waits_for_its_backoff(self, store):
        js = MemoryJobStore(store)
        job = js.enqueue(
            idempotency_key="k1", user_key="u",
            now="2026-01-01T00:00:00+00:00", max_attempts=3,
        )
        js.claim("u", job.id, now="2026-01-01T00:00:00+00:00")
        js.fail("u", job.id, error="x", now="2026-01-01T00:00:00+00:00")
        assert js.claim("u", now="2026-01-01T00:00:05+00:00") is None
        assert js.claim("u", now="2026-01-01T00:01:00+00:00") is not None

    def test_recover_stale_returns_abandoned_processing_jobs(self, store):
        js = MemoryJobStore(store)
        job = js.enqueue(
            idempotency_key="k1", user_key="u", now="2026-01-01T00:00:00+00:00"
        )
        js.claim("u", job.id, now="2026-01-01T00:00:00+00:00")
        # Fresh claim -> not stale.
        assert (
            js.recover_stale(
                "u", now="2026-01-01T00:05:00+00:00", stale_after_seconds=900
            )
            == 0
        )
        # Long after the claim -> recovered.
        assert (
            js.recover_stale(
                "u", now="2026-01-01T01:00:00+00:00", stale_after_seconds=900
            )
            == 1
        )
        recovered = js.get("u", job.id)
        assert recovered is not None and recovered.state == "retrying"
        assert js.claim("u", now="2026-01-01T01:00:01+00:00") is not None

    def test_extraction_key_is_stable_per_range(self):
        assert extraction_key("c1", "r1") == extraction_key("c1", "r1")
        assert extraction_key("c1", "r1") != extraction_key("c1", "r2")


class TestDurableSchedule:
    def _inline(self, monkeypatch):
        monkeypatch.setattr(engine, "background_pipeline", lambda: False)

    def test_schedule_runs_via_a_durable_job(self, hybrid, ids, monkeypatch):
        self._inline(monkeypatch)
        monkeypatch.setattr(engine, "durable_jobs", lambda: True)
        _seed_turn(hybrid, ids)
        engine.schedule_process_run_end(
            hybrid,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
            state="done",
            run_id="run1",
        )
        js = MemoryJobStore(hybrid.base)
        stored = js.find_by_key(
            ids["user_key"], extraction_key(ids["conversation_id"], "run1")
        )
        assert stored is not None
        assert stored.state == "completed"
        assert stored.attempts == 1
        # The pipeline really ran.
        assert (
            hybrid.read_working_memory(
                ids["user_key"], ids["space_id"], ids["project_id"]
            )
            is not None
        )

    def test_same_run_does_not_create_a_second_job(self, hybrid, ids, monkeypatch):
        self._inline(monkeypatch)
        monkeypatch.setattr(engine, "durable_jobs", lambda: True)
        _seed_turn(hybrid, ids)
        for _ in range(2):
            engine.schedule_process_run_end(
                hybrid,
                user_key=ids["user_key"],
                space_id=ids["space_id"],
                project_id=ids["project_id"],
                conversation_id=ids["conversation_id"],
                run_id="run1",
            )
        js = MemoryJobStore(hybrid.base)
        key = extraction_key(ids["conversation_id"], "run1")
        assert len([j for j in js.read_jobs(ids["user_key"]) if j.idempotency_key == key]) == 1

    def test_flag_off_runs_directly_without_a_job(self, hybrid, ids, monkeypatch):
        self._inline(monkeypatch)
        monkeypatch.setattr(engine, "durable_jobs", lambda: False)
        _seed_turn(hybrid, ids)
        engine.schedule_process_run_end(
            hybrid,
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
            run_id="run1",
        )
        assert MemoryJobStore(hybrid.base).read_jobs(ids["user_key"]) == []
        assert (
            hybrid.read_working_memory(
                ids["user_key"], ids["space_id"], ids["project_id"]
            )
            is not None
        )


class TestRestartRecovery:
    def test_pending_job_from_a_previous_process_is_completed(self, hybrid, ids):
        # A run enqueued its job, then the process died before the worker ran.
        MemoryJobStore(hybrid.base).enqueue(
            idempotency_key=extraction_key(ids["conversation_id"], "run1"),
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
            run_id="run1",
            run_state="done",
            now="2026-01-01T00:00:00+00:00",
        )
        _seed_turn(hybrid, ids)
        # Restart: a fresh drain recovers and runs it.
        completed = engine.drain_memory_jobs(hybrid, ids["user_key"])
        assert completed == 1
        job = MemoryJobStore(hybrid.base).find_by_key(
            ids["user_key"], extraction_key(ids["conversation_id"], "run1")
        )
        assert job is not None and job.state == "completed"

    def test_abandoned_processing_job_is_recovered(self, hybrid, ids):
        js = MemoryJobStore(hybrid.base)
        job = js.enqueue(
            idempotency_key=extraction_key(ids["conversation_id"], "run_crash"),
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
            run_id="run_crash",
            now="2026-01-01T00:00:00+00:00",
        )
        # Claimed with no timestamp == a torn/abandoned claim (worker crashed).
        js.claim(ids["user_key"], job.id, now="")
        _seed_turn(hybrid, ids)
        completed = engine.drain_memory_jobs(hybrid, ids["user_key"])
        assert completed == 1
        assert js.get(ids["user_key"], job.id).state == "completed"

    def test_failed_extraction_is_recorded_not_raised(self, hybrid, ids, monkeypatch):
        js = MemoryJobStore(hybrid.base)
        js.enqueue(
            idempotency_key=extraction_key(ids["conversation_id"], "run1"),
            user_key=ids["user_key"],
            space_id=ids["space_id"],
            project_id=ids["project_id"],
            conversation_id=ids["conversation_id"],
            run_id="run1",
            now="2026-01-01T00:00:00+00:00",
        )

        def _boom(*_a, **_k):
            raise RuntimeError("extract failed")

        monkeypatch.setattr(engine, "process_run_end", _boom)
        completed = engine.drain_memory_jobs(hybrid, ids["user_key"])
        assert completed == 0
        job = js.find_by_key(
            ids["user_key"], extraction_key(ids["conversation_id"], "run1")
        )
        assert job is not None
        assert job.state == "retrying"
        assert "extract failed" in job.last_error
