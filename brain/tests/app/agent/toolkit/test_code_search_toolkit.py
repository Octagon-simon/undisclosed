# ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========
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

from app.agent.toolkit.code_search_toolkit import CodeSearchToolkit

pytestmark = pytest.mark.unit


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "app.py").write_text("needle = 1\n", encoding="utf-8")
    (tmp_path / "keep.md").write_text("needle docs\n", encoding="utf-8")
    (tmp_path / "app.py.20261018_120000.bak").write_text(
        "needle = 0\n", encoding="utf-8"
    )
    (tmp_path / "notes.orig").write_text("needle old\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def toolkit(workspace):
    return CodeSearchToolkit(
        api_task_id="test-task", working_directory=str(workspace)
    )


def test_grep_search_skips_scratch_files(toolkit):
    out = toolkit.grep_search("needle")

    assert "app.py:" in out
    assert "keep.md:" in out
    assert ".bak" not in out
    assert ".orig" not in out


def test_list_dir_skips_scratch_files(toolkit):
    out = toolkit.list_dir()

    assert "app.py" in out
    assert "keep.md" in out
    assert ".bak" not in out
    assert ".orig" not in out
