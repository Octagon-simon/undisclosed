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

"""Router + hybrid ranking tests (§18, §21-22)."""

from __future__ import annotations

from app.memory.hybrid import ranking, router
from app.memory.hybrid.schema import (
    LEVEL_EPISODES,
    LEVEL_EXACT,
    LEVEL_MEMORY,
    LEVEL_RECENT,
    RetrievedItem,
)


class TestRouter:
    def test_continuation_stays_on_recent(self):
        plan = router.route("continue")
        assert plan.level == LEVEL_RECENT
        assert plan.use_semantic is False
        assert plan.use_lexical is False

    def test_exact_query_runs_exact_lane(self):
        plan = router.route("what exact timeout did we settle on")
        assert plan.level == LEVEL_EXACT
        assert plan.use_exact is True
        assert plan.use_lexical is True

    def test_historical_query_runs_episode_lane(self):
        plan = router.route("what did we decide about authentication")
        assert plan.level == LEVEL_EPISODES
        assert plan.use_semantic is True

    def test_current_state_query_uses_memory(self):
        plan = router.route("what database are we using")
        assert plan.level == LEVEL_MEMORY
        assert plan.use_memory is True

    def test_default_query_has_reasons(self):
        plan = router.route("implement the export feature")
        assert plan.use_memory is True
        assert plan.reasons

    def test_escalation_when_nothing_found(self):
        plan = router.route("what database are we using")
        escalated = router.escalate(plan, found=False)
        assert escalated.level > plan.level
        assert escalated.use_exact is True


class TestRanking:
    def test_semantic_signal_raises_score(self):
        low = ranking.score_item(
            RetrievedItem(kind="episode", id="a", text="x"), "database"
        )
        high = ranking.score_item(
            RetrievedItem(kind="episode", id="b", text="x"),
            "database",
            semantic=1.0,
        )
        assert high.score > low.score

    def test_entity_match_helps_exact_query(self):
        plain = ranking.score_item(
            RetrievedItem(kind="message", id="a", text="Turn 1 (assistant): use it"),
            "what port",
        )
        exact = ranking.score_item(
            RetrievedItem(
                kind="message", id="b", text="Turn 2 (assistant): port 8080"
            ),
            "what port",
        )
        assert exact.score > plain.score

    def test_rerank_orders_desc_and_truncates(self):
        items = [
            RetrievedItem(kind="episode", id="a", text="auth", scores={"semantic": 0.1}),
            RetrievedItem(kind="episode", id="b", text="auth", scores={"semantic": 0.9}),
        ]
        out = ranking.rerank(items, "auth", max_turn=10, top_k=1)
        assert len(out) == 1
        assert out[0].id == "b"

    def test_recency_score_bounds(self):
        assert ranking.recency_score(10, 10) == 1.0
        import math

        assert math.isclose(ranking.recency_score(1, 11), 0.0, abs_tol=1e-9)
        assert ranking.recency_score(None, 10) == 0.0

    def test_recency_prefers_newer(self):
        items = [
            RetrievedItem(kind="episode", id="old", text="auth", turn=1),
            RetrievedItem(kind="episode", id="new", text="auth", turn=20),
        ]
        out = ranking.rerank(items, "auth", max_turn=20)
        assert out[0].id == "new"
