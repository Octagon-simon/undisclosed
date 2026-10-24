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

"""Tests for ``scripts/rekey_hybrid_constraints.py``.

The migration touches a user's real store, so the contract under test is what
matters: dry run changes nothing, apply rewrites only the key, collisions are
left alone, a backup holds the original bytes, and a second run is a no-op.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from app.memory.hybrid import canonical

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "rekey_hybrid_constraints.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("rekey_hybrid", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rekey = _load_script()


def _row(memory_id: str, key: str, value: str) -> dict:
    return {
        "id": memory_id,
        "conversation_id": "p",
        "type": "constraint",
        "key": key,
        "value": value,
        "status": "active",
        "created_at": "2026-09-20T00:00:00+00:00",
        "updated_at": "2026-09-20T00:00:00+00:00",
    }


def _store(tmp_path: Path) -> tuple[Path, Path]:
    path = (
        tmp_path
        / "users"
        / "user_1"
        / "spaces"
        / "s1"
        / "projects"
        / "p1"
        / "memories.json"
    )
    path.parent.mkdir(parents=True)
    return tmp_path, path


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps({"memories": rows}, indent=2), encoding="utf-8")


def _read(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["memories"]


def test_dry_run_reports_without_writing(tmp_path):
    root, path = _store(tmp_path)
    _write(path, [_row("mem_1", "constraint", "not post a new top-level message")])

    changes, collisions, written = rekey._process(
        path, root, apply=False, backup_root=root / "backup"
    )

    assert (changes, collisions, written) == (1, 0, False)
    assert _read(path)[0]["key"] == "constraint"
    assert not (root / "backup").exists()


def test_apply_rewrites_key_and_keeps_a_backup(tmp_path):
    root, path = _store(tmp_path)
    value = "not post a new top-level message"
    _write(path, [_row("mem_1", "constraint", value)])
    original = path.read_text(encoding="utf-8")

    changes, _, written = rekey._process(
        path, root, apply=True, backup_root=root / "backup"
    )

    assert (changes, written) == (1, True)
    assert _read(path)[0]["key"] == canonical.rule_key(value)
    backup = root / "backup" / path.relative_to(root)
    assert backup.read_text(encoding="utf-8") == original


def test_collision_is_reported_and_left_untouched(tmp_path):
    root, path = _store(tmp_path)
    value = "not post a new top-level message"
    _write(
        path,
        [
            _row("mem_1", "constraint", value),
            _row("mem_2", canonical.rule_key(value), "already here"),
        ],
    )

    changes, collisions, written = rekey._process(
        path, root, apply=True, backup_root=root / "backup"
    )

    assert (changes, collisions, written) == (0, 1, False)
    assert [row["key"] for row in _read(path)] == ["constraint", canonical.rule_key(value)]


def test_apply_is_idempotent(tmp_path):
    root, path = _store(tmp_path)
    _write(path, [_row("mem_1", "constraint", "not commit yet")])

    rekey._process(path, root, apply=True, backup_root=root / "backup")
    changes, collisions, written = rekey._process(
        path, root, apply=True, backup_root=root / "backup"
    )

    assert (changes, collisions, written) == (0, 0, False)


def test_non_constraint_rows_are_ignored(tmp_path):
    root, path = _store(tmp_path)
    fact = _row("mem_1", "constraint", "anything")
    fact["type"] = "fact"
    _write(path, [fact])

    assert rekey._process(
        path, root, apply=True, backup_root=root / "backup"
    ) == (0, 0, False)
