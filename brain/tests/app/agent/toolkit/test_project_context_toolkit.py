# Copyright (c) 2026 Simon Ugorji
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

import os

import pytest

from app.agent.toolkit import project_context_toolkit as pct

SAMPLE = '''\
import os


def greet(name):
    return f"hi {name}"
'''

DOC_SAMPLE = '''\
"""module doc."""
import os


def greet(name):
    """say hi."""
    return f"hi {name}"
'''

BASE_NS = 1_700_000_000_000_000_000


@pytest.fixture
def ctx_root(tmp_path, monkeypatch):
    root = tmp_path / "ctx"
    monkeypatch.setattr(pct, "_context_root", lambda: root)
    return root


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _write(ws / "sample.py", SAMPLE, 0)
    return ws


def _write(path, text, tick):
    path.write_text(text, encoding="utf-8")
    ns = BASE_NS + tick * 1_000_000
    os.utime(path, ns=(ns, ns))


def _toolkit(workspace):
    return pct.ProjectContextToolkit(
        api_task_id="test-task", working_directory=str(workspace)
    )


def test_first_scan_indexes_files(ctx_root, workspace):
    out = _toolkit(workspace).project_changes()
    assert "No stored fingerprints yet" in out
    assert "indexed 1 source files" in out


def test_repeat_scan_reports_nothing(ctx_root, workspace):
    tk = _toolkit(workspace)
    tk.project_changes()
    assert "Nothing changed" in tk.project_changes()


def test_comment_only_change_is_partial(ctx_root, workspace):
    tk = _toolkit(workspace)
    tk.project_changes()
    _write(workspace / "sample.py", SAMPLE + "\n# a note\n", 1)
    out = tk.project_changes()
    assert "PARTIAL" in out
    assert "sample.py" in out
    assert "ARCHITECTURE" not in out


def test_docstring_only_change_is_partial(ctx_root, workspace):
    _write(workspace / "sample.py", DOC_SAMPLE, 0)
    tk = _toolkit(workspace)
    tk.project_changes()
    _write(workspace / "sample.py", DOC_SAMPLE.replace("say hi.", "say hello."), 1)
    out = tk.project_changes()
    assert "PARTIAL" in out
    assert "ARCHITECTURE" not in out


def test_body_change_is_full(ctx_root, workspace):
    tk = _toolkit(workspace)
    tk.project_changes()
    _write(
        workspace / "sample.py",
        SAMPLE.replace("hi {name}", "hello {name}"),
        1,
    )
    out = tk.project_changes()
    assert "FULL" in out
    assert "ARCHITECTURE" not in out


def test_signature_change_is_architecture(ctx_root, workspace):
    tk = _toolkit(workspace)
    tk.project_changes()
    _write(
        workspace / "sample.py",
        SAMPLE.replace("def greet(name):", "def greet(name, punct):"),
        1,
    )
    out = tk.project_changes()
    assert "ARCHITECTURE" in out
    assert "+" in out


def test_import_change_is_architecture(ctx_root, workspace):
    tk = _toolkit(workspace)
    tk.project_changes()
    _write(workspace / "sample.py", SAMPLE.replace("import os", "import sys\nimport os"), 1)
    out = tk.project_changes()
    assert "ARCHITECTURE" in out
    assert "imports changed" in out


def test_deleted_file_is_reported(ctx_root, workspace):
    tk = _toolkit(workspace)
    tk.project_changes()
    (workspace / "sample.py").unlink()
    out = tk.project_changes()
    assert "ARCHITECTURE" in out
    assert "(deleted)" in out


class _FakeProc:
    def __init__(self, stdout):
        self.stdout = stdout


def test_digest_cache_ignores_comment_edits(ctx_root, workspace, monkeypatch):
    repomix_calls = []

    def fake_run(cmd, **_kwargs):
        if "repomix@latest" in cmd:
            repomix_calls.append(cmd)
            return _FakeProc("DIGEST BODY")
        return _FakeProc("abc123abc123")

    monkeypatch.setattr(pct.subprocess, "run", fake_run)
    monkeypatch.setattr(pct.shutil, "which", lambda _name: "/usr/bin/npx")
    tk = _toolkit(workspace)

    assert "DIGEST BODY" in tk.understand_project(full=True)
    assert len(repomix_calls) == 1

    _write(workspace / "sample.py", SAMPLE + "\n# a note\n", 1)
    cached = tk.understand_project(full=True)
    assert "cached project digest" in cached
    assert "DIGEST BODY" in cached
    assert "1 partial" in cached
    assert len(repomix_calls) == 1

    _write(
        workspace / "sample.py",
        SAMPLE.replace("hi {name}", "hello {name}"),
        2,
    )
    regenerated = tk.understand_project(full=True)
    assert "DIGEST BODY" in regenerated
    assert "1 full" in regenerated
    assert len(repomix_calls) == 2


def test_time_limited_entry_is_deepened_without_reporting_a_change(
    ctx_root, workspace, monkeypatch
):
    monkeypatch.setattr(pct, "_FP_SCAN_BUDGET_S", 0.0)
    monkeypatch.setattr(pct, "_FP_DEEPEN_BUDGET_S", 0.0)
    files, changes, _ = pct._scan(str(workspace), {})
    assert files["sample.py"]["shallow"] == "budget"
    assert changes and changes[0]["level"] == pct._LEVEL_ARCHITECTURE

    monkeypatch.setattr(pct, "_FP_SCAN_BUDGET_S", 10.0)
    monkeypatch.setattr(pct, "_FP_DEEPEN_BUDGET_S", 3.0)
    files, changes, _ = pct._scan(str(workspace), files)
    assert not files["sample.py"].get("shallow")
    assert "function_definition:greet(1)" in files["sample.py"]["symbols"]
    assert changes == []


def test_unparsable_entry_is_not_retried(ctx_root, workspace, monkeypatch):
    monkeypatch.setattr(pct, "_FP_PARSE_MAX_BYTES", 0)
    files, _, _ = pct._scan(str(workspace), {})
    assert files["sample.py"]["shallow"] == "static"

    files, changes, _ = pct._scan(str(workspace), files)
    assert files["sample.py"]["shallow"] == "static"
    assert changes == []


def _index(workspace, layout):
    for rel, text in layout.items():
        path = workspace / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        _write(path, text, 0)
    files, _, _ = pct._scan(str(workspace), {})
    pct._save_store(str(workspace), files, "head")
    return files


def test_python_import_resolves_across_package_prefix(ctx_root, workspace):
    _index(
        workspace,
        {
            "brain/app/service/task.py": "class Agents:\n    pass\n",
            "brain/app/service/chat.py": (
                "from app.service.task import Agents\n\n\ndef run():\n"
                "    return Agents\n"
            ),
        },
    )
    rows = {row["path"]: row for row in pct.read_order(str(workspace))}
    assert rows["brain/app/service/task.py"]["fan_in"] == 1
    assert rows["brain/app/service/chat.py"]["depth"] == 1


def test_relative_js_import_resolves(ctx_root, workspace):
    _index(
        workspace,
        {
            "agent-ui/src/lib/util.ts": "export const a = 1\n",
            "agent-ui/src/app.tsx": "import { a } from './lib/util'\n",
        },
    )
    rows = {row["path"]: row for row in pct.read_order(str(workspace))}
    assert rows["agent-ui/src/lib/util.ts"]["fan_in"] == 1


def test_read_order_skips_tests_and_unknown_stores(ctx_root, workspace):
    assert pct.read_order(str(workspace)) == []
    _index(
        workspace,
        {
            "brain/app/core.py": "def core():\n    pass\n",
            "brain/tests/app/test_core.py": (
                "from app.core import core\n\n\ndef test_core():\n    core()\n"
            ),
        },
    )
    paths = [row["path"] for row in pct.read_order(str(workspace))]
    assert "brain/tests/app/test_core.py" not in paths
    assert paths[0] == "brain/app/core.py"


def test_read_order_formats_counts(ctx_root, workspace):
    _index(
        workspace,
        {
            "brain/app/core.py": "def core():\n    pass\n",
            "brain/app/use.py": "from app.core import core\n",
        },
    )
    text = pct._format_read_order(pct.read_order(str(workspace), limit=2))
    assert "Read order" in text
    assert "1 dep)" in text or "1 dep," in text


def test_import_cycle_terminates(ctx_root, workspace):
    _index(
        workspace,
        {
            "a.py": "import b\n",
            "b.py": "import a\n",
        },
    )
    rows = pct.read_order(str(workspace))
    assert {row["path"] for row in rows} >= {"a.py", "b.py"}


def test_js_directory_import_resolves_to_index(ctx_root, workspace):
    _index(
        workspace,
        {
            "agent-ui/src/components/index.ts": "export const X = 1\n",
            "agent-ui/src/app.tsx": "import { X } from './components'\n",
        },
    )
    rows = {row["path"]: row for row in pct.read_order(str(workspace))}
    assert rows["agent-ui/src/components/index.ts"]["fan_in"] == 1


def test_tsconfig_alias_import_resolves(ctx_root, workspace):
    _index(
        workspace,
        {
            "agent-ui/tsconfig.json": (
                '{"compilerOptions": {"baseUrl": "./", '
                '"paths": {"@/*": ["src/*"]}}}'
            ),
            "agent-ui/src/lib/util.ts": "export const a = 1\n",
            "agent-ui/src/app.tsx": 'import { a } from "@/lib/util"\n',
        },
    )
    rows = {row["path"]: row for row in pct.read_order(str(workspace))}
    assert rows["agent-ui/src/lib/util.ts"]["fan_in"] == 1


def test_tsconfig_alias_tolerates_comments_and_trailing_commas(ctx_root, workspace):
    _index(
        workspace,
        {
            "web/tsconfig.json": (
                "{\n"
                "  // the app root\n"
                '  "compilerOptions": {\n'
                '    "baseUrl": ".",\n'
                '    "paths": { "~/*": ["./app/*"] },\n'
                "  },\n"
                "}\n"
            ),
            "web/app/store/auth.ts": "export const token = 1\n",
            "web/app/page.tsx": 'import { token } from "~/store/auth"\n',
        },
    )
    rows = {row["path"]: row for row in pct.read_order(str(workspace))}
    assert rows["web/app/store/auth.ts"]["fan_in"] == 1


def test_alias_uses_nearest_tsconfig(ctx_root, workspace):
    _index(
        workspace,
        {
            "pkg-a/tsconfig.json": '{"compilerOptions": {"paths": {"#/*": ["lib/*"]}}}',
            "pkg-b/tsconfig.json": '{"compilerOptions": {"paths": {"#/*": ["src/*"]}}}',
            "pkg-a/lib/x.ts": "export const x = 1\n",
            "pkg-b/src/y.ts": "export const y = 1\n",
            "pkg-a/entry.ts": 'import { x } from "#/x"\n',
            "pkg-b/entry.ts": 'import { y } from "#/y"\n',
        },
    )
    rows = {row["path"]: row for row in pct.read_order(str(workspace))}
    assert rows["pkg-a/lib/x.ts"]["fan_in"] == 1
    assert rows["pkg-b/src/y.ts"]["fan_in"] == 1


def test_alias_does_not_resolve_third_party(ctx_root, workspace):
    _index(
        workspace,
        {
            "agent-ui/tsconfig.json": '{"compilerOptions": {"paths": {"@/*": ["src/*"]}}}',
            "agent-ui/src/app.tsx": 'import { Button } from "@/ui/button"\n',
        },
    )
    rows = {row["path"]: row for row in pct.read_order(str(workspace))}
    assert rows["agent-ui/src/app.tsx"]["deps"] == 0


def test_gitignored_files_are_pruned(ctx_root, workspace):
    import subprocess

    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    (workspace / ".gitignore").write_text("lib/\n", encoding="utf-8")
    _index(
        workspace,
        {
            "lib/bundle.js": "const a = 1\n",
            "src/app.ts": "export const a = 1\n",
        },
    )
    _, files = pct._load_store(str(workspace))
    assert "lib/bundle.js" not in files
    assert "src/app.ts" in files


def test_knowledge_graph_is_written_one_node_per_line(ctx_root, workspace):
    import json

    _index(
        workspace,
        {
            "brain/app/core.py": "def core():\n    pass\n",
            "brain/app/use.py": "from app.core import core\n",
        },
    )
    path = pct.write_knowledge_graph(str(workspace))
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    #the workspace fixture seeds sample.py as a third file
    assert data["files"] == len(data["nodes"]) == 3
    assert data["tour"][0]["path"] == "brain/app/core.py"
    node_lines = [ln for ln in text.splitlines() if ln.strip().startswith('{"path"')]
    assert len(node_lines) == 3


def test_knowledge_graph_staleness_reports_missing_file(ctx_root, workspace):
    stale, reasons = pct.graph_staleness(str(workspace))
    assert stale is True
    assert reasons


def test_knowledge_graph_staleness_rejects_old_scan_version(ctx_root, workspace):
    import json

    _index(workspace, {"a.py": "x = 1\n"})
    path = pct.write_knowledge_graph(str(workspace))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["scan_version"] = pct._FP_VERSION - 1
    path.write_text(json.dumps(data), encoding="utf-8")
    stale, reasons = pct.graph_staleness(str(workspace))
    assert stale is True
    assert "scan version" in reasons[0]


def test_fresh_graph_is_not_stale(ctx_root, workspace):
    _index(workspace, {"brain/app/core.py": "def core():\n    pass\n"})
    pct.write_knowledge_graph(str(workspace))
    stale, reasons = pct.graph_staleness(str(workspace))
    assert stale is False
    assert reasons == []


def test_body_change_marks_graph_stale(ctx_root, workspace):
    _index(workspace, {"brain/app/core.py": "def core():\n    pass\n"})
    pct.write_knowledge_graph(str(workspace))
    _write(workspace / "brain/app/core.py", "def core(flag):\n    return flag\n", 5)
    stale, reasons = pct.graph_staleness(str(workspace))
    assert stale is True
    assert "code changed" in reasons[0]


def test_comment_change_keeps_graph_fresh(ctx_root, workspace):
    _index(workspace, {"brain/app/core.py": "def core():\n    pass\n"})
    pct.write_knowledge_graph(str(workspace))
    _write(
        workspace / "brain/app/core.py",
        "def core():\n    #unrelated note\n    pass\n",
        5,
    )
    stale, _ = pct.graph_staleness(str(workspace))
    assert stale is False
