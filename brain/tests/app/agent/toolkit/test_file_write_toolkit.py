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
# ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.agent.toolkit.file_write_toolkit import FileToolkit
from app.service.task import create_task_lock, task_locks


@pytest.fixture
def toolkit(tmp_path: Path) -> Iterator[FileToolkit]:
    api_task_id = f"file-toolkit-test-{tmp_path.name}"
    lock = create_task_lock(api_task_id)
    lock.working_directory = str(tmp_path)
    try:
        yield FileToolkit(api_task_id, working_directory=str(tmp_path))
    finally:
        task_locks.pop(api_task_id, None)


def test_backup_is_enabled_by_default(toolkit: FileToolkit, tmp_path: Path) -> None:
    assert toolkit.backup_enabled is True

    target = tmp_path / "app.py"
    target.write_text("one\n")
    toolkit.edit_file("app.py", "one", "two")

    assert target.read_text() == "two\n"
    backups = list(tmp_path.glob("app.py.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text() == "one\n"


def test_editing_a_backup_does_not_create_another(
    toolkit: FileToolkit, tmp_path: Path
) -> None:
    scratch = tmp_path / "app.py.20260101_000000.bak"
    scratch.write_text("old\n")

    assert toolkit._create_backup(scratch) is None
    assert list(tmp_path.glob("*.bak.bak")) == []


def test_delete_files_removes_a_file_inside_the_workspace(
    toolkit: FileToolkit, tmp_path: Path
) -> None:
    target = tmp_path / "old-component.tsx"
    target.write_text("export {}\n")

    result = toolkit.delete_files("old-component.tsx")

    assert "Deleted:" in result
    assert not target.exists()


def test_delete_files_refuses_a_path_outside_the_workspace(
    toolkit: FileToolkit, tmp_path: Path
) -> None:
    outside = tmp_path.parent / "outside-eigent.txt"
    outside.write_text("keep\n")

    result = toolkit.delete_files(str(outside))

    assert "outside the workspace" in result
    assert outside.exists()


def test_delete_files_refuses_to_escape_with_parent_segments(
    toolkit: FileToolkit, tmp_path: Path
) -> None:
    outside = tmp_path.parent / "escape-eigent.txt"
    outside.write_text("keep\n")

    result = toolkit.delete_files("../escape-eigent.txt")

    assert "outside the workspace" in result
    assert outside.exists()


def test_delete_files_refuses_the_workspace_root(
    toolkit: FileToolkit, tmp_path: Path
) -> None:
    result = toolkit.delete_files(".")
    assert "workspace root" in result
    assert tmp_path.exists()


def test_delete_files_refuses_git_metadata(
    toolkit: FileToolkit, tmp_path: Path
) -> None:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("[core]\n")

    result = toolkit.delete_files(".git", recursive=True)

    assert "git metadata" in result
    assert git_dir.exists()


def test_delete_files_requires_recursive_for_non_empty_dirs(
    toolkit: FileToolkit, tmp_path: Path
) -> None:
    folder = tmp_path / "legacy"
    folder.mkdir()
    (folder / "keep.ts").write_text("x\n")

    refused = toolkit.delete_files("legacy")
    assert "recursive=True" in refused
    assert folder.exists()

    removed = toolkit.delete_files("legacy", recursive=True)
    assert "Deleted:" in removed
    assert not folder.exists()


def test_delete_files_refuses_a_symlink_to_outside(
    toolkit: FileToolkit, tmp_path: Path
) -> None:
    outside = tmp_path.parent / "linked-eigent.txt"
    outside.write_text("keep\n")
    link = tmp_path / "link.txt"
    link.symlink_to(outside)

    result = toolkit.delete_files("link.txt")

    assert "outside the workspace" in result
    assert outside.exists()


def test_delete_files_is_registered_as_a_tool(toolkit: FileToolkit) -> None:
    names = {tool.get_function_name() for tool in toolkit.get_tools()}
    assert "delete_files" in names
    assert "write_to_file" in names
    assert "list_backups" in names
    assert "restore_backup" in names


def test_read_file_reads_a_backup_copy(
    toolkit: FileToolkit, tmp_path: Path
) -> None:
    backup = tmp_path / "app.py.20260101_000000.bak"
    backup.write_text("original\n")

    result = toolkit.read_file("app.py.20260101_000000.bak")

    assert isinstance(result, str)
    assert "original" in result


def test_list_backups_finds_hidden_copies(
    toolkit: FileToolkit, tmp_path: Path
) -> None:
    target = tmp_path / "app.py"
    target.write_text("one\n")
    toolkit.edit_file("app.py", "one", "two")

    result = toolkit.list_backups("app.py")

    assert "Backups for" in result
    assert ".bak" in result


def test_list_backups_reports_when_there_are_none(
    toolkit: FileToolkit, tmp_path: Path
) -> None:
    (tmp_path / "app.py").write_text("one\n")

    assert "No backups found" in toolkit.list_backups("app.py")


def test_restore_newest_backup_reverts_the_edit(
    toolkit: FileToolkit, tmp_path: Path
) -> None:
    target = tmp_path / "app.py"
    target.write_text("one\n")
    toolkit.edit_file("app.py", "one", "two")

    result = toolkit.restore_backup("app.py")

    assert "Restored:" in result
    assert target.read_text() == "one\n"
    #the post-edit contents stay recoverable, so the restore can be undone
    backups = [p.read_text() for p in tmp_path.glob("app.py.*.bak")]
    assert "two\n" in backups
    assert "one\n" in backups


def test_restore_specific_backup(
    toolkit: FileToolkit, tmp_path: Path
) -> None:
    (tmp_path / "app.py.20260101_000000.bak").write_text("first\n")
    (tmp_path / "app.py.20260102_000000.bak").write_text("second\n")
    target = tmp_path / "app.py"
    target.write_text("current\n")

    result = toolkit.restore_backup(
        "app.py", "app.py.20260101_000000.bak"
    )

    assert "Restored:" in result
    assert target.read_text() == "first\n"


def test_restore_refuses_a_file_that_is_not_a_backup(
    toolkit: FileToolkit, tmp_path: Path
) -> None:
    (tmp_path / "app.py.20260101_000000.bak").write_text("first\n")
    (tmp_path / "other.txt").write_text("not a backup\n")
    target = tmp_path / "app.py"
    target.write_text("current\n")

    result = toolkit.restore_backup("app.py", "other.txt")

    assert "is not a backup of" in result
    assert target.read_text() == "current\n"


def test_restore_refuses_a_path_outside_the_workspace(
    toolkit: FileToolkit, tmp_path: Path
) -> None:
    outside = tmp_path.parent / "outside-eigent.txt"
    outside.write_text("keep\n")

    result = toolkit.restore_backup(str(outside))

    assert "outside the workspace" in result
    assert outside.read_text() == "keep\n"
