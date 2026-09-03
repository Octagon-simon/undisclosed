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
"""Folder == Project conversation history.

Product model: "a project is basically a folder; any open folder in this editor
is a project and every project must own its conversations." These tests pin the
no-duplicate guarantees of that model end-to-end through the REST surface the
agent History panel drives (Space project listing + per-project replay fetch):
"""
import os
import json
import pytest
from pathlib import Path

pytestmark = pytest.mark.unit

from app.controller import chat_platform_controller as ctrl  # noqa: E402


@pytest.fixture
def isolated_brain(tmp_path, monkeypatch):
    """Redirect ALL persistence into a throw-away tmp dir."""
    home = tmp_path / "undisclosed"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ctrl, "_home", lambda: home)
    turns = home / "turns"
    turns.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ctrl, "_turns_root", lambda: turns)
    return ctrl, turns


@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(ctrl.router, prefix="/api/v1")
    with TestClient(app) as tc:
        yield tc


def _write_chat(turns: Path, chat_id: str, prompts: list):
    """Create <turns>/<chat_id>/turn_*.json fragments exactly as the brain does."""
    d = chat_id.replace("/", "_")
    chat_dir = turns / d
    chat_dir.mkdir(parents=True, exist_ok=True)
    for idx, content in enumerate(prompts):
        payload = {
            "chatId": chat_id,
            "queryId": chat_id,
            "runId": chat_id,
            "timestamp": 1600000000 + idx,
            "userMessage": {"content": content},
            "type": "USER",
        }
        (chat_dir / ("turn_%d.json" % idx)).write_text(
            json.dumps(payload), encoding="utf-8"
        )
    return chat_dir


def _open_folder(client, root, name):
    r = client.post(
        "/api/v1/spaces",
        json={"source_type": "folder", "root_path": root, "name": name},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_folder_owns_its_conversations_no_duplicates(isolated_brain, client):
    """A single logical conversation fragmented into several identical on-disk
    chat dirs must project ONCE (regression guard for duplicated history)."""
    _, turns = isolated_brain
    # Real chat dirs are slash-free (the on-device store sanitises ids), so an
    # id below maps 1:1 to a directory and can be replayed through the path
    # routed grouped endpoint. Three distinct dirs share the SAME first prompt,
    # simulating one logical conversation re-minted several times by the live
    # session store; they must collapse to a single history row.
    _write_chat(turns, "dup-1", ["How do I deploy eigent?"])
    _write_chat(turns, "dup-2", ["How do I deploy eigent?"])
    _write_chat(turns, "dup-3", ["How do I deploy eigent?"])
    _write_chat(turns, "rest-1", ["Write a REST endpoint please."])

    space = _open_folder(client, "/work/project-a", "project-a")
    projects = client.get("/api/v1/spaces/%s/projects" % space["id"]).json()

    distinct = {p["name"] for p in projects}
    assert distinct == {"How do I deploy eigent?", "Write a REST endpoint please."}
    assert len(projects) == 2, "no duplicate rows allowed"

    # Clicking a row replays that exact conversation on disk.
    row = next(p for p in projects if p["name"] == "How do I deploy eigent?")
    grouped = client.get("/api/v1/chat/histories/grouped/%s" % row["id"]).json()
    assert grouped.get("project_id") == row["id"]
    assert grouped.get("task_count", 0) >= 1


def test_folder_is_path_stable_same_id(isolated_brain, client):
    """Re-opening the same folder yields the same stable space + single list."""
    _, turns = isolated_brain
    _write_chat(turns, "chat/9", ["Only chat in this folder."])

    a = _open_folder(client, "/same/folder", "folder")
    b = _open_folder(client, "/same/folder", "folder")
    assert a["id"] == b["id"]

    pa = client.get("/api/v1/spaces/%s/projects" % a["id"]).json()
    pb = client.get("/api/v1/spaces/%s/projects" % b["id"]).json()
    assert len(pa) == len(pb) == 1
    assert pa == pb


def test_folder_does_not_leak_other_folder_chats(isolated_brain, client):
    """Folder B never surfaces Folder A's conversations (no cross-folder dup)."""
    _, turns = isolated_brain
    _write_chat(turns, "aaa/proj", ["chat bound to project A"])
    _write_chat(turns, "proj/bbb", ["chat that belongs to B"])

    sa = _open_folder(client, "/p/a", "A")
    sb = _open_folder(client, "/p/b", "B")

    pb = client.get("/api/v1/spaces/%s/projects" % sb["id"]).json()
    b_ids = {p["id"] for p in pb}
    # Space B must not contain A's 'chat bound to project A'.
    a_chat_id = "aaa_proj"
    assert a_chat_id not in b_ids, "cross-folder leak: A chat shown in B"


def test_legacy_space_lists_all_but_still_no_duplicates(isolated_brain, client):
    """Generic device space lists every conversation exactly once."""
    _, turns = isolated_brain
    _write_chat(turns, "x/1", ["duplicate hello"])
    _write_chat(turns, "x/1", ["duplicate hello"])

    r = client.get("/api/v1/spaces/legacy")
    assert r.status_code == 200
    legacy_id = r.json()["id"]
    projects = client.get("/api/v1/spaces/%s/projects" % legacy_id).json()
    names = [p["name"] for p in projects]
    assert names.count("duplicate hello") == 1, "row duplicated"
