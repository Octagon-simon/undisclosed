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

import pytest

from app.agent.tool_rag import ToolRAGSelector, _core_toolkit_markers

pytestmark = pytest.mark.unit

_COVERAGE_TOOLS = ("coverage_gap_plan", "run_tests", "read_test_skill")


class _FakeTool:
    def __init__(self, name: str, toolkit: str) -> None:
        self._toolkit_name = toolkit
        self._name = name

    def get_function_name(self) -> str:
        return self._name

    def get_function_schema(self, format_type=None):
        return {
            "name": self._name,
            "description": "fake",
            "parameters": {"type": "object", "properties": {}},
        }


def test_test_runner_is_an_always_on_core_toolkit():
    assert any("test runner" in marker for marker in _core_toolkit_markers())

    tools = [_FakeTool(name, "Test Runner Toolkit") for name in _COVERAGE_TOOLS]
    selector = ToolRAGSelector(tools)

    # Core, not retrievable: a coverage check must never need load_capability
    # or a query that happens to embed close to "coverage".
    assert selector.core_names == set(_COVERAGE_TOOLS)
    assert selector.loadable_toolkits() == {}
