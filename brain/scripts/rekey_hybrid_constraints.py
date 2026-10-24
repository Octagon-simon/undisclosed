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

"""Re-key legacy constraints stored under the shared ``"constraint"`` key.

Old extractor versions fell back to the literal key ``constraint`` whenever no
known noun occurred in the message, so two different rules shared one identity.
New writes derive the key from the rule's wording; this tool brings old records
in line so a later restatement merges instead of superseding the wrong rule.

Dry-run by default. ``--apply`` rewrites the key only: no record is dropped,
deleted, or reworded, and a collision is reported and left untouched.

Usage:
    python scripts/rekey_hybrid_constraints.py
    python scripts/rekey_hybrid_constraints.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.memory.hybrid import canonical  # noqa: E402


def _memory_files(root: Path) -> list[Path]:
    user_root = root / "users"
    if not user_root.is_dir():
        return []
    files = list(user_root.glob("*/memories.json"))
    files.extend(user_root.glob("*/spaces/*/projects/*/memories.json"))
    return sorted(files)


def _plan(rows: list[dict]) -> tuple[list[tuple[dict, str]], list[dict]]:
    """Return ``(changes, collisions)`` for one memories.json payload."""

    active = [
        row
        for row in rows
        if row.get("status") == "active" and row.get("type") == "constraint"
    ]
    taken = {
        canonical.normalize_key(str(row.get("key") or ""))
        for row in active
        if str(row.get("key") or "").strip().lower() != "constraint"
    }
    changes: list[tuple[dict, str]] = []
    collisions: list[dict] = []
    for row in active:
        if str(row.get("key") or "").strip().lower() != "constraint":
            continue
        new_key = canonical.rule_key(str(row.get("value") or ""))
        if canonical.normalize_key(new_key) in taken:
            collisions.append(row)
            continue
        taken.add(canonical.normalize_key(new_key))
        changes.append((row, new_key))
    return changes, collisions


def _process(path: Path, *, apply: bool) -> tuple[int, int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0, 0
    rows = payload.get("memories") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return 0, 0

    changes, collisions = _plan(rows)
    for row, new_key in changes:
        print(f"{path}\n  {row.get('id')}: constraint -> {new_key}\n    {row.get('value')}")
    for row in collisions:
        print(
            f"{path}\n  SKIP {row.get('id')}: derived key already taken\n"
            f"    {row.get('value')}"
        )
    if apply and changes:
        for row, new_key in changes:
            row["key"] = new_key
            row["updated_at"] = datetime.now(UTC).isoformat()
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return len(changes), len(collisions)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.home() / ".undisclosed" / "memory",
        help="memory root (default: ~/.undisclosed/memory)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the new keys (default: report only)",
    )
    args = parser.parse_args()

    files = _memory_files(args.root)
    total_changes = 0
    total_collisions = 0
    for path in files:
        changes, collisions = _process(path, apply=args.apply)
        total_changes += changes
        total_collisions += collisions

    verb = "Re-keyed" if args.apply else "Would re-key"
    print(
        f"\n{verb} {total_changes} record(s) across {len(files)} file(s); "
        f"{total_collisions} collision(s) left untouched."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
