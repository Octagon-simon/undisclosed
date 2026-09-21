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

"""Semantic project matching (§14).

§14 lists "semantic similarity against project descriptions" next to lexical
matching. This suite pins the signal itself
(:mod:`app.memory.hybrid.project_semantic`) and its blend into project
resolution (:mod:`app.memory.hybrid.resolver`), using a deterministic concept
embedder so no model, disk or network is touched.
"""

from __future__ import annotations

import re

import pytest

from app.memory import LocalMemoryStore
from app.memory.events import ProjectMemory
from app.memory.hybrid import project_semantic
from app.memory.hybrid.config import (
    enabled,
    project_semantic_cosine_floor,
    project_semantic_enabled,
    project_semantic_max_projects,
    project_semantic_min_chars,
    project_semantic_weight,
)
from app.memory.hybrid.project import ProjectStore
from app.memory.hybrid.resolver import CONFIDENCE_FLOOR, resolve, score_projects
from app.memory.hybrid.schema import Project


class _ConceptEmbedder:
    """Maps a text to a 3-dim concept vector by keyword, so "eat" == "meal".

    Two texts about the same concept have cosine 1.0 (score 1.0 after rescale);
    two texts about different concepts have cosine 0.0, which sits below the
    cosine floor and is reported as "no signal". Unmatched text gets an
    orthogonal vector.
    """

    _CONCEPTS = {
        "food": ("eat", "meal", "nutrition", "food", "recipe", "pantry"),
        "weather": ("weather", "forecast", "temperature", "rain"),
    }
    _VECTORS = {"food": [1.0, 0.0, 0.0], "weather": [0.0, 1.0, 0.0]}
    _OTHER = [0.0, 0.0, 1.0]

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        low = text.lower()
        for concept, words in self._CONCEPTS.items():
            # Word-boundary match, so "weather" does not trip the "eat" keyword.
            if any(re.search(rf"\b{word}\b", low) for word in words):
                return list(self._VECTORS[concept])
        return list(self._OTHER)


def _project(project_id: str, name: str, description: str) -> Project:
    return Project(id=project_id, name=name, description=description)


def _write_project(
    store: LocalMemoryStore, user_key: str, space_id: str, project_id: str, name: str
) -> None:
    store.write_project(
        user_key,
        ProjectMemory(
            project_id=project_id,
            space_id=space_id,
            name=name,
            created_at="t",
            updated_at="t",
        ),
    )


def _store_projects(
    store: LocalMemoryStore, rows: list[tuple[str, str, str, str]]
) -> ProjectStore:
    ps = ProjectStore(store)
    for space_id, project_id, name, description in rows:
        _write_project(store, "u", space_id, project_id, name)
        ps.ensure(
            "u",
            project_id=project_id,
            space_id=space_id,
            name=name,
            description=description,
            now="t",
        )
    return ps


@pytest.fixture(autouse=True)
def _semantic_on(monkeypatch):
    """Force the semantic signal on for the whole module; tests that need it
    off flip the env flag themselves. State is reset around every test so the
    module-level caches never leak between cases."""

    monkeypatch.setenv("UNDISCLOSED_HYBRID_PROJECT_SEMANTIC", "1")
    project_semantic.reset()
    yield
    project_semantic.reset()


class TestSemanticScores:
    def test_scores_by_description_not_words(self):
        # The request shares no words with the description -- only the meaning.
        scores = project_semantic.semantic_scores(
            "the app that tracks what I eat",
            [
                _project("meal", "Pantry", "meal planning and nutrition tracker"),
                _project("wx", "Sky", "weather forecast dashboard"),
            ],
            embedder=_ConceptEmbedder(),
        )
        assert scores["meal"] == pytest.approx(1.0)
        assert "wx" not in scores

    def test_unrelated_description_is_absent(self):
        scores = project_semantic.semantic_scores(
            "what will the weather be tomorrow",
            [_project("meal", "Pantry", "meal planning and nutrition tracker")],
            embedder=_ConceptEmbedder(),
        )
        assert scores == {}

    def test_projects_without_a_description_are_skipped(self):
        embedder = _ConceptEmbedder()
        scores = project_semantic.semantic_scores(
            "the app that tracks what I eat",
            [_project("a", "Alpha", ""), _project("b", "Beta", "   ")],
            embedder=embedder,
        )
        assert scores == {}
        assert embedder.calls == 0  # never even loads the model

    def test_description_shorter_than_floor_is_ignored(self, monkeypatch):
        monkeypatch.setenv("UNDISCLOSED_HYBRID_PROJECT_SEMANTIC_MIN_CHARS", "40")
        scores = project_semantic.semantic_scores(
            "the app that tracks what I eat",
            [_project("meal", "Pantry", "meal planner")],
            embedder=_ConceptEmbedder(),
        )
        assert scores == {}

    def test_short_query_yields_no_signal(self):
        assert (
            project_semantic.semantic_scores(
                "hi", [_project("meal", "Pantry", "meal planning")], embedder=_ConceptEmbedder()
            )
            == {}
        )

    def test_disabled_signal_returns_empty(self):
        project_semantic.set_embedder(_ConceptEmbedder())
        project_semantic.disable()
        assert (
            project_semantic.semantic_scores(
                "the app that tracks what I eat",
                [_project("meal", "Pantry", "meal planning and nutrition tracker")],
            )
            == {}
        )

    def test_vectors_are_cached_across_calls(self):
        embedder = _ConceptEmbedder()
        projects = [
            _project("meal", "Pantry", "meal planning and nutrition tracker"),
            _project("wx", "Sky", "weather forecast dashboard"),
        ]
        project_semantic.semantic_scores(
            "the app that tracks what I eat", projects, embedder=embedder
        )
        # 1 query + 2 descriptions.
        assert embedder.calls == 3
        project_semantic.semantic_scores(
            "the app that tracks what I eat", projects, embedder=embedder
        )
        assert embedder.calls == 3  # all cached, nothing re-embedded

    def test_changed_description_is_re_embedded(self):
        embedder = _ConceptEmbedder()
        # Neutral name, so the embedded text is driven by the description alone.
        project = _project("meal", "Atlas", "meal planning and nutrition tracker")
        project_semantic.semantic_scores(
            "the app that tracks what I eat", [project], embedder=embedder
        )
        project.description = "weather forecast dashboard"
        scores = project_semantic.semantic_scores(
            "the app that tracks what I eat", [project], embedder=embedder
        )
        assert scores == {}  # the edit invalidated the cached vector

    def test_embedder_failure_is_swallowed(self):
        def _boom(_texts):
            raise RuntimeError("model exploded")

        assert (
            project_semantic.semantic_scores(
                "the app that tracks what I eat",
                [_project("meal", "Pantry", "meal planning and nutrition tracker")],
                embedder=_boom,
            )
            == {}
        )

    def test_only_description_carrying_projects_are_embedded_and_capped(
        self, monkeypatch
    ):
        monkeypatch.setenv("UNDISCLOSED_HYBRID_PROJECT_SEMANTIC_MAX", "1")
        embedder = _ConceptEmbedder()
        project_semantic.semantic_scores(
            "the app that tracks what I eat",
            [
                _project("meal", "Pantry", "meal planning and nutrition tracker"),
                _project("cook", "Kitchen", "recipe book for home cooks"),
            ],
            embedder=embedder,
        )
        # 1 query + at most 1 description (the cap), never both.
        assert embedder.calls <= 2


class TestConfigKnobs:
    def test_weight_default_and_clamps(self, monkeypatch):
        monkeypatch.delenv("UNDISCLOSED_HYBRID_W_PROJECT_SEMANTIC", raising=False)
        assert project_semantic_weight() == pytest.approx(0.6)
        monkeypatch.setenv("UNDISCLOSED_HYBRID_W_PROJECT_SEMANTIC", "5")
        assert project_semantic_weight() == 1.0
        monkeypatch.setenv("UNDISCLOSED_HYBRID_W_PROJECT_SEMANTIC", "-2")
        assert project_semantic_weight() == 0.0

    def test_floor_default_and_clamps(self, monkeypatch):
        monkeypatch.delenv("UNDISCLOSED_HYBRID_PROJECT_SEMANTIC_FLOOR", raising=False)
        assert project_semantic_cosine_floor() == pytest.approx(0.35)
        monkeypatch.setenv("UNDISCLOSED_HYBRID_PROJECT_SEMANTIC_FLOOR", "1.5")
        assert project_semantic_cosine_floor() == 0.95

    def test_max_projects_is_at_least_one(self, monkeypatch):
        monkeypatch.setenv("UNDISCLOSED_HYBRID_PROJECT_SEMANTIC_MAX", "0")
        assert project_semantic_max_projects() == 1

    def test_min_chars_is_non_negative(self, monkeypatch):
        monkeypatch.setenv("UNDISCLOSED_HYBRID_PROJECT_SEMANTIC_MIN_CHARS", "-5")
        assert project_semantic_min_chars() == 0

    def test_default_follows_master_switch(self, monkeypatch):
        monkeypatch.delenv("UNDISCLOSED_HYBRID_PROJECT_SEMANTIC", raising=False)
        monkeypatch.delenv("UNDISCLOSED_HYBRID_MEMORY", raising=False)
        assert project_semantic_enabled() is enabled()
        monkeypatch.setenv("UNDISCLOSED_HYBRID_MEMORY", "1")
        assert project_semantic_enabled() is True

    def test_explicit_flag_overrides_master_switch(self, monkeypatch):
        monkeypatch.setenv("UNDISCLOSED_HYBRID_MEMORY", "0")
        monkeypatch.setenv("UNDISCLOSED_HYBRID_PROJECT_SEMANTIC", "1")
        assert project_semantic_enabled() is True


class TestScoreProjectsBlend:
    def test_semantic_is_added_on_top_of_lexical(self):
        scored = score_projects(
            "unrelated request",
            [_project("x", "Sky", "")],
            semantic={"x": 1.0},
        )
        assert scored[0][1] == pytest.approx(0.6)  # 0 lexical + 0.6 * 1.0

    def test_blend_clamps_to_one_and_leaves_named_projects(self, monkeypatch):
        monkeypatch.setenv("UNDISCLOSED_HYBRID_W_PROJECT_SEMANTIC", "0.9")
        # "Mac app" is named outright (lexical 0.95); semantic must not exceed 1.
        scored = score_projects(
            "Mac app", [_project("x", "Mac app", "")], semantic={"x": 1.0}
        )
        assert scored[0][1] == 1.0

    def test_absent_map_is_pure_lexical(self):
        with_map = score_projects("alpha", [_project("x", "Alpha", "")])
        without = score_projects(
            "alpha", [_project("x", "Alpha", "")], semantic={}
        )
        assert with_map[0][1] == without[0][1]

    def test_zero_weight_disables_blend(self, monkeypatch):
        monkeypatch.setenv("UNDISCLOSED_HYBRID_W_PROJECT_SEMANTIC", "0")
        scored = score_projects(
            "unrelated request", [_project("x", "Sky", "")], semantic={"x": 1.0}
        )
        assert scored[0][1] == 0.0


class TestResolverSemanticBlend:
    def test_description_hit_resolves_when_no_words_overlap(self, store):
        project_semantic.set_embedder(_ConceptEmbedder())
        ps = _store_projects(
            store,
            [
                ("s1", "meal", "Pantry", "meal planning and nutrition tracker"),
                ("s2", "wx", "Sky", "weather forecast dashboard"),
            ],
        )
        r = resolve(ps, "u", query="the app that tracks what I eat")
        assert r.confident
        assert r.project_id == "meal"
        assert r.reason == "semantic_match"
        assert r.confidence >= CONFIDENCE_FLOOR

    def test_named_project_skips_the_embedder(self, store):
        embedder = _ConceptEmbedder()
        project_semantic.set_embedder(embedder)
        ps = _store_projects(
            store,
            [
                ("s1", "chefly", "CheflyMenu", "meal planning and nutrition tracker"),
                ("s2", "wx", "Sky", "weather forecast dashboard"),
            ],
        )
        r = resolve(ps, "u", query="continue the CheflyMenu")
        assert r.project_id == "chefly"
        assert r.reason == "name_match"
        assert embedder.calls == 0  # the common case never pays for embeddings

    def test_semantic_cannot_override_a_named_project(self, store):
        embedder = _ConceptEmbedder()
        project_semantic.set_embedder(embedder)
        ps = _store_projects(
            store,
            [
                ("s1", "chefly", "CheflyMenu", "meal planning and nutrition tracker"),
                ("s2", "wx", "Sky", "weather forecast dashboard"),
            ],
        )
        # A description hit ("meal planner") must not beat the project named.
        r = resolve(ps, "u", query="continue CheflyMenu, the meal planner")
        assert r.project_id == "chefly"
        assert r.reason == "name_match"

    def test_all_unrelated_stays_unresolved(self, store):
        project_semantic.set_embedder(_ConceptEmbedder())
        ps = _store_projects(
            store,
            [
                ("s1", "meal", "Pantry", "meal planning and nutrition tracker"),
                ("s2", "wx", "Sky", "weather forecast dashboard"),
            ],
        )
        r = resolve(ps, "u", query="the gizmo that frobnicates")
        assert not r.confident
        assert r.project_id == ""
        assert r.reason == "none"

    def test_signal_off_falls_back_to_pure_lexical(self, store, monkeypatch):
        monkeypatch.setenv("UNDISCLOSED_HYBRID_PROJECT_SEMANTIC", "0")
        project_semantic.set_embedder(_ConceptEmbedder())
        ps = _store_projects(
            store,
            [
                ("s1", "meal", "Pantry", "meal planning and nutrition tracker"),
                ("s2", "wx", "Sky", "weather forecast dashboard"),
            ],
        )
        r = resolve(ps, "u", query="the app that tracks what I eat")
        assert not r.confident
        assert r.project_id == ""

    def test_semantic_resolution_links_the_conversation(self, store):
        project_semantic.set_embedder(_ConceptEmbedder())
        ps = _store_projects(
            store,
            [
                ("s1", "meal", "Pantry", "meal planning and nutrition tracker"),
                ("s2", "wx", "Sky", "weather forecast dashboard"),
            ],
        )
        r = resolve(ps, "u", conversation_id="c1", query="the app that tracks what I eat")
        assert r.project_id == "meal"
        ref = ps.project_for_conversation("u", "c1")
        assert ref is not None and ref.project_id == "meal"
