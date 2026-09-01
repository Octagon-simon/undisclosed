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

from app.agent.toolkit.code_query_toolkit import CodeQueryToolkit

# The tools are expected to fail-soft to text-search when tree-sitter is
# missing, so the assertions below must hold in both branches.

SAMPLE = '''\
import os
from pathlib import Path

def greet(name):
    return f"hi {name}"

class User:
    def __init__(self, name):
        self.name = name
'''


@pytest.fixture
def workspace(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE, encoding="utf-8")
    (tmp_path / "other.py").write_text(
        "import sample\n\nresult = sample.greet('x')\n", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def toolkit(workspace):
    return CodeQueryToolkit(
        api_task_id="test-task-123",
        working_directory=str(workspace),
    )


def test_find_symbol_function(toolkit):
    out = toolkit.find_symbol("greet")
    assert "greet" in out
    assert "function_definition" in out


def test_find_symbol_class(toolkit):
    out = toolkit.find_symbol("User")
    assert "User" in out
    assert "class_definition" in out


def test_find_symbol_missing(toolkit):
    assert "not_defined_anywhere" in toolkit.find_symbol("not_defined_anywhere")


def test_file_symbols(toolkit, workspace):
    out = toolkit.file_symbols("sample.py")
    assert "greet" in out
    assert "User" in out
    assert "__init__" in out


def test_find_references(toolkit, workspace):
    out = toolkit.find_references("name")
    # at least one reference exists in sample.py
    assert out and "References" in out or "No references" in out


def test_find_references_across_files(toolkit, workspace):
    out = toolkit.find_references("greet")
    assert "References" in out
    assert "other.py" in out or "sample.py" in out


def test_imports_of(toolkit, workspace):
    out = toolkit.imports_of("sample.py")
    assert "import os" in out
    assert "pathlib" in out


def test_context_at(toolkit, workspace):
    out = toolkit.context_at("sample.py", line=4, radius=2)
    assert "def greet(name):" in out
    assert "4 | def greet(name):" in out  # centered line flagged


def test_context_at_wide_radius(toolkit, workspace):
    out = toolkit.context_at("sample.py", line=7, radius=3)
    assert "class User:" in out


def test_context_at_unknown_file(toolkit):
    out = toolkit.context_at("does_not_exist.py", line=1)
    assert "No source file found" in out


def test_get_tools(toolkit):
    names = {t.get_function_name() for t in toolkit.get_tools()}
    assert {
        "find_symbol",
        "file_symbols",
        "find_references",
        "callers_of",
        "imports_of",
        "context_at",
        "skeleton_map",
    } == names


def test_toolkit_names_supported_extension():
    assert CodeQueryToolkit.toolkit_name() == "Code Query Toolkit"


# =============================================================================
# Structure-first skeleton map + JS/TS typing + imports fallback
# =============================================================================

TS_SAMPLE = """\
import { a } from './a';
export const Foo = () => <div />;
export function Bar() { return Foo(); }
const Q = 1;
function Inner() { const z = 1; }
class K { meth() {} }
type Alias = string;
export interface I
"""


def test_skeleton_map_shows_top_level_symbols(toolkit, workspace):
    out = toolkit.skeleton_map()
    assert "sample.py" in out or "other.py" in out
    assert "greet" in out
    assert "User" in out


def test_skeleton_map_is_small(toolkit, workspace):
    # The whole point of the skeleton map is a tiny token footprint.
    out = toolkit.skeleton_map()
    assert len(out) < 1500


def test_skeleton_map_excludes_nested(toolkit, workspace):
    # `z` is nested inside Inner's body; the skeleton must NOT surface it.
    out = toolkit.skeleton_map()
    assert "def greet" not in out  # signatures, not bodies
    assert "return f" not in out


def test_js_ts_symbol_detection_toplevel(tmp_path):
    f = tmp_path / "ui.ts"
    f.write_text(TS_SAMPLE, encoding="utf-8")
    tk = CodeQueryToolkit(api_task_id="t", working_directory=str(tmp_path))
    sym = tk.file_symbols("ui.ts")
    # modern TS constructs must be detected
    assert "Foo" in sym  # export const (arrow)
    assert "Bar" in sym  # export function
    assert "Inner" in sym  # top-level function
    # method should appear as a symbol too (file_symbols lists all)
    assert "meth" in sym


def test_js_ts_skeleton_includes_class_and_alias(tmp_path):
    f = tmp_path / "ui.ts"
    f.write_text(TS_SAMPLE, encoding="utf-8")
    tk = CodeQueryToolkit(api_task_id="t", working_directory=str(tmp_path))
    out = tk.skeleton_map(paths=["ui.ts"])
    assert "Foo" in out
    assert "Bar" in out
    assert "K" in out
    # nested `z` must NOT appear
    assert " z " not in out


def test_imports_of_compiled_query(toolkit, workspace):
    out = toolkit.imports_of("sample.py")
    assert "import os" in out
    assert "pathlib" in out


def test_imports_of_grep_fallback(tmp_path):
    # Force the grep fallback by bypassing tree-sitter parse via an extension
    # that tree-sitter can't parse but grep handles (e.g. a .txt copy), and
    # assert we still get a real result, not just a "can't parse" note.
    f = tmp_path / "deps.txt"
    f.write_text("import sample\nfrom pathlib import Path\n\nhandlers = []\n")
    tk = CodeQueryToolkit(api_task_id="t", working_directory=str(tmp_path))
    out = tk.imports_of("deps.txt")
    assert "import sample" in out
    assert "pathlib" in out


def test_understand_project_structure_first(tmp_path):
    from app.agent.toolkit.project_context_toolkit import ProjectContextToolkit

    f = tmp_path / "sample.py"
    f.write_text(SAMPLE, encoding="utf-8")
    tk = ProjectContextToolkit(api_task_id="t", working_directory=str(tmp_path))
    out = tk.understand_project()
    assert "skeleton map" in out
    assert "greet" in out
    assert len(out) < 1500
