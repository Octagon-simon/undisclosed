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

"""Text utilities + lexical/exact retrieval tests (§17)."""

from __future__ import annotations

from app.memory.events import ConversationEvent
from app.memory.hybrid import lexical
from app.memory.hybrid import text as T


def _event(i: int, role: str, content: str) -> ConversationEvent:
    return ConversationEvent(
        event_id=f"evt_{i}",
        run_id=f"run_{i}",
        timestamp="t",
        role=role,  # type: ignore[arg-type]
        content=content,
        source="chat",
        visibility="context",
        hash="sha256:x",
    )


class TestText:
    def test_tokenize_keeps_identifiers(self):
        tokens = T.tokenize("Deploy app.py to https://api.example.com/v2 at 8080")
        assert "app.py" in tokens
        assert "8080" in tokens
        assert "https://api.example.com/v2" in tokens

    def test_tokenize_drops_stopwords(self):
        assert "the" not in T.tokenize("the database")

    def test_entities_extracts_exact_details(self):
        found = T.entities("timeout 45s, port 5432, v1.2.3, file main.py")
        assert "45s" in found
        assert "v1.2.3" in found
        assert "main.py" in found

    def test_keyword_overlap(self):
        assert T.keyword_overlap("auth flow design", "auth flow") > 0.5
        assert T.keyword_overlap("auth flow", "database schema") == 0.0


class TestLexical:
    def _events(self):
        return [
            _event(1, "user", "How should we structure the authentication flow?"),
            _event(2, "assistant", "Use a JWT with a refresh token."),
            _event(3, "user", "What port should the server listen on?"),
            _event(4, "assistant", "Use port 8080 for local development."),
        ]

    def test_search_finds_relevant_message(self):
        results = lexical.search(self._events(), "authentication refresh token", k=2)
        assert results
        assert results[0][2].content.startswith("Use a JWT")

    def test_search_empty_query_is_empty(self):
        assert lexical.search(self._events(), "") == []

    def test_exact_matches_prefers_value_bearing_message(self):
        results = lexical.exact_matches(
            self._events(), "what exact port did we use", k=3
        )
        assert results
        assert "8080" in results[0][2].content

    def test_exact_matches_ignores_filler_only_terms(self):
        # A query made only of filler words and no entities -> no matches.
        assert lexical.exact_matches(self._events(), "what did we do", k=3) == []

    def test_exact_matches_none_on_absence(self):
        assert (
            lexical.exact_matches(self._events(), "what commit hash", k=3) == []
        )

    def test_index_messages_skips_empty_content(self):
        events = [_event(1, "user", "hi"), _event(2, "assistant", "  ")]
        assert [i for i, _e in lexical.index_messages(events)] == [1]
