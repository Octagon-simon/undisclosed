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

"""Patch-coverage parity with lacuna's `analyze @diff` pipeline."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.agent.toolkit.test_runner_toolkit import (
    TestRunnerToolkit,
    _align_report_to_changed,
    _FileCoverage,
    _LineHit,
    _parse_pass_count,
    _parse_scope,
    _parse_unified_diff,
    _Report,
)


def _report(files: list[_FileCoverage]) -> _Report:
    total = sum(len(f.lines) for f in files)
    covered = sum(sum(1 for ln in f.lines if ln.hit > 0) for f in files)
    return _Report(files, (covered / total) if total else 1.0, 1.0)


def _file(path: str, hits: list[int]) -> _FileCoverage:
    lines = [_LineHit(number, hit) for number, hit in enumerate(hits, start=1)]
    covered = sum(1 for ln in lines if ln.hit > 0)
    return _FileCoverage(path, lines, [], covered / len(lines), 1.0)


@pytest.fixture
def toolkit(tmp_path: Path) -> TestRunnerToolkit:
    return TestRunnerToolkit(api_task_id="t", working_directory=str(tmp_path))


def test_scope_parses_diff_ref_and_directory(tmp_path: Path) -> None:
    directory = tmp_path / "packages" / "api"
    directory.mkdir(parents=True)

    scope_dir, want_diff, ref, unknown = _parse_scope(
        "@diff:develop packages/api", tmp_path
    )

    assert scope_dir == directory.resolve()
    assert want_diff is True
    assert ref == "develop"
    assert unknown is None


def test_scope_keeps_a_bare_token_for_ref_resolution(tmp_path: Path) -> None:
    _, want_diff, _, unknown = _parse_scope("develop", tmp_path)

    assert want_diff is False
    assert unknown == "develop"


def test_pass_count_ignores_the_test_files_line() -> None:
    assert _parse_pass_count("Tests  1 failed | 15 passed (16)") == 15
    assert _parse_pass_count("Test Files  1 passed (1)") == 0
    assert _parse_pass_count("============ 9 passed in 0.01s ============") == 9


def test_aligns_package_relative_report_paths(tmp_path: Path) -> None:
    changed = {str(tmp_path / "packages" / "api" / "src" / "foo.ts"): {1, 2}}
    report = _report([_file("src/foo.ts", [1, 0])])

    aligned = _align_report_to_changed(
        report, changed, tmp_path / "packages" / "api"
    )

    assert aligned.files[0].path == str(
        tmp_path / "packages" / "api" / "src" / "foo.ts"
    )


def test_does_not_realign_on_an_ambiguous_suffix(tmp_path: Path) -> None:
    changed = {
        str(tmp_path / "a" / "src" / "foo.ts"): {1},
        str(tmp_path / "b" / "src" / "foo.ts"): {1},
    }
    report = _report([_file("src/foo.ts", [0])])

    aligned = _align_report_to_changed(report, changed, tmp_path)

    assert aligned is report


def test_diff_mode_keeps_partially_covered_files(tmp_path: Path) -> None:
    # 95% covered: below the 100% patch gate but above the 80% file threshold.
    hits = [1] * 19 + [0]
    toolkit = TestRunnerToolkit(api_task_id="t", working_directory=str(tmp_path))
    report = _report([_file(str(tmp_path / "src" / "a.ts"), hits)])

    assert toolkit._extract_gaps(report, 80) == []
    assert len(toolkit._extract_gaps(report, 101)) == 1


def test_narrow_to_diff_and_patch_count(
    toolkit: TestRunnerToolkit, tmp_path: Path
) -> None:
    source = tmp_path / "src" / "a.ts"
    source.parent.mkdir(parents=True)
    source.write_text("export function run() {\n  return 1\n}\n", encoding="utf-8")

    report = _report([_file(str(source), [1, 1, 0, 0])])
    gaps = toolkit._extract_gaps(report, 101)
    changed = {str(source): {3, 4, 9}}  # 9 is not executable

    narrowed, assume = toolkit._narrow_to_diff(gaps, changed, report, [])

    assert [(g.file_path, g.uncovered_lines) for g in narrowed] == [
        (str(source), [3, 4])
    ]
    assert assume == set()
    pct, covered, total = toolkit._patch_coverage(report, changed, assume)
    assert (covered, total) == (0, 2)
    assert pct == 0.0


def test_changed_file_without_a_coverage_record_is_assumed_uncovered(
    toolkit: TestRunnerToolkit, tmp_path: Path
) -> None:
    source = tmp_path / "src" / "new.ts"
    source.parent.mkdir(parents=True)
    source.write_text(
        "export function fresh() {\n  return 2\n}\n", encoding="utf-8"
    )
    changed = {str(source): {1, 2}}

    narrowed, assume = toolkit._narrow_to_diff([], changed, _report([]), [])

    assert assume == {str(source)}
    assert narrowed[0].uncovered_lines == [1, 2]
    _, covered, total = toolkit._patch_coverage(_report([]), changed, assume)
    assert (covered, total) == (0, 2)


def test_unified_diff_collects_changed_new_side_lines() -> None:
    diff = (
        "diff --git a/src/a.py b/src/a.py\n"
        "--- a/src/a.py\n"
        "+++ b/src/a.py\n"
        "@@ -1,0 +2,3 @@\n"
        "+one\n"
        "+two\n"
        "+three\n"
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1 +1 @@\n"
        "+docs\n"
    )

    changed = _parse_unified_diff(diff, "/repo")

    assert changed == {"/repo/src/a.py": {2, 3, 4}}


def test_resolve_diff_plus_untracked_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "a.ts").write_text("export const a = 1;\n", encoding="utf-8")

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
        )

    git("init", "-q", "-b", "main")
    git("-c", "user.email=a@b", "-c", "user.name=t", "add", "-A")
    git("-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "init")

    fresh = repo / "src" / "b.ts"
    fresh.write_text("export const b = 2;\n", encoding="utf-8")
    toolkit = TestRunnerToolkit(api_task_id="t", working_directory=str(repo))

    base, changed = toolkit._resolve_diff("main")

    assert base == "main"
    assert changed[str(fresh)] == {1}

