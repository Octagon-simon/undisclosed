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

"""Storage-root selection: ~/.undisclosed is canonical, ~/eigent is legacy."""

from pathlib import Path

from app.utils.workspace_paths import (
    get_storage_root,
    project_task_root,
    storage_root_candidates,
)


def test_fresh_install_uses_dot_undisclosed(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert get_storage_root() == tmp_path / ".undisclosed"


def test_legacy_eigent_root_used_when_dot_undisclosed_absent(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / "eigent").mkdir()

    assert get_storage_root() == tmp_path / "eigent"


def test_dot_undisclosed_wins_but_legacy_root_stays_readable(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".undisclosed").mkdir()
    (tmp_path / "eigent").mkdir()

    assert get_storage_root() == tmp_path / ".undisclosed"
    assert storage_root_candidates() == [
        tmp_path / ".undisclosed",
        tmp_path / "eigent",
    ]


def test_project_task_root_is_under_dot_undisclosed(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert project_task_root("alice@example.com", "p1", "t1", "42") == (
        tmp_path
        / ".undisclosed"
        / "user_42"
        / "project_p1"
        / "task_t1"
    )
