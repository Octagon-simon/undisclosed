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

"""Shared fixtures for the memory tests.

The autouse fixture disables the chromadb episode index so no test ever reads or
writes the real ``~/.undisclosed/memory`` tree. Tests that specifically exercise
the vector layer inject a fake collection instead.
"""

from __future__ import annotations

import pytest

from app.memory import LocalMemoryStore
from app.memory.hybrid import vector
from app.memory.hybrid.storage import HybridStore


@pytest.fixture(autouse=True)
def _disable_vector_index() -> None:
    vector.disable()
    yield
    vector.reset()


@pytest.fixture
def store(tmp_path) -> LocalMemoryStore:
    return LocalMemoryStore(root=tmp_path / "memory")


@pytest.fixture
def hybrid(store: LocalMemoryStore) -> HybridStore:
    return HybridStore(store)


@pytest.fixture
def ids() -> dict[str, str]:
    return {
        "user_key": "user_42",
        "space_id": "space_test",
        "project_id": "project_test",
        "conversation_id": "project_test",
    }
