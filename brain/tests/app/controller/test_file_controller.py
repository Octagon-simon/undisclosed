# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
# Portions Copyright 2026 Simon Ugorji. All Rights Reserved.
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

import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile

from app.controller import file_controller
from app.utils import file_utils


def test_resolve_project_root_prefers_user_id_root(
    monkeypatch, tmp_path, caplog
):
    eigent_root = tmp_path / "eigent"
    user_project = eigent_root / "user_20" / "project_p1"
    user_project.mkdir(parents=True)
    (eigent_root / "other_user" / "project_p1").mkdir(parents=True)

    monkeypatch.setattr(
        file_controller, "_get_storage_root", lambda: eigent_root
    )

    resolved = file_controller._resolve_project_root(
        "yueming.lai@example.com", "p1", "20"
    )

    assert resolved == user_project
    assert "Resolved project root via fallback lookup" not in caplog.text


def test_resolve_project_root_falls_back_to_legacy_email_root(
    monkeypatch, tmp_path
):
    eigent_root = tmp_path / "eigent"
    legacy_project = eigent_root / "yueming.lai" / "project_p1"
    legacy_project.mkdir(parents=True)

    monkeypatch.setattr(
        file_controller, "_get_storage_root", lambda: eigent_root
    )

    resolved = file_controller._resolve_project_root(
        "yueming.lai@example.com", "p1", "20"
    )

    assert resolved == legacy_project


def test_resolve_project_root_does_not_fallback_to_other_user_root(
    monkeypatch, tmp_path
):
    eigent_root = tmp_path / "eigent"
    (eigent_root / "user_20" / "project_p1").mkdir(parents=True)
    expected = eigent_root / "user_42" / "project_p1"

    monkeypatch.setattr(
        file_controller, "_get_storage_root", lambda: eigent_root
    )

    resolved = file_controller._resolve_project_root(
        "yueming.lai@example.com", "p1", "42"
    )

    assert resolved == expected


def test_resolve_project_root_without_user_id_stays_email_scoped(
    monkeypatch, tmp_path
):
    eigent_root = tmp_path / "eigent"
    (eigent_root / "user_20" / "project_p1").mkdir(parents=True)
    expected = eigent_root / "yueming.lai" / "project_p1"

    monkeypatch.setattr(
        file_controller, "_get_storage_root", lambda: eigent_root
    )

    resolved = file_controller._resolve_project_root(
        "yueming.lai@example.com", "p1"
    )

    assert resolved == expected


# --- upload / attach serving ------------------------------------------------


class _FakeState:
    def __init__(self, session_id: str | None):
        if session_id is not None:
            self.session_id = session_id


class _FakeRequest:
    def __init__(self, session_id: str | None):
        self.state = _FakeState(session_id)


def _upload_file(name: str = "notes.txt", data: bytes = b"hello"):
    return UploadFile(file=BytesIO(data), filename=name)


def test_upload_without_header_uses_middleware_session(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(file_controller, "_get_workspace_root", lambda: tmp_path)

    result = asyncio.run(
        file_controller.upload_file(
            request=_FakeRequest("sess_minted"),
            file=_upload_file(),
            x_session_id=None,
        )
    )

    assert result["session_id"] == "sess_minted"
    assert result["file_id"].startswith("upload://sess_minted/")
    stored = tmp_path / "sess_minted" / "uploads" / result["file_id"].split("/")[-1]
    assert stored.is_file()


def test_upload_without_any_session_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(file_controller, "_get_workspace_root", lambda: tmp_path)

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(
            file_controller.upload_file(
                request=_FakeRequest(None),
                file=_upload_file(),
                x_session_id=None,
            )
        )

    assert excinfo.value.status_code == 400


def _pin_workspace(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(file_controller, "_get_workspace_root", lambda: root)
    monkeypatch.setattr(file_utils, "env", lambda *a, **k: str(root))


def _store_upload(root, session: str, name: str, data: bytes = b"img") -> Path:
    target = root / session / "uploads" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def test_upload_content_serves_a_legacy_ref_without_a_session(
    monkeypatch, tmp_path
):
    _pin_workspace(monkeypatch, tmp_path)
    stored = _store_upload(tmp_path, "sess_owner", "pic.png_1700000000000")

    response = asyncio.run(
        file_controller.upload_content(
            file_id="upload://pic.png_1700000000000", session_id=None
        )
    )

    assert response.path == str(stored)


def test_upload_content_survives_a_drifted_session(monkeypatch, tmp_path):
    _pin_workspace(monkeypatch, tmp_path)
    stored = _store_upload(tmp_path, "sess_owner", "pic.png_1700000000000")

    response = asyncio.run(
        file_controller.upload_content(
            file_id="upload://pic.png_1700000000000", session_id="sess_other"
        )
    )

    assert response.path == str(stored)


def test_upload_content_prefers_the_ref_session(monkeypatch, tmp_path):
    _pin_workspace(monkeypatch, tmp_path)
    stored = _store_upload(tmp_path, "sess_owner", "pic.png_1700000000000")

    response = asyncio.run(
        file_controller.upload_content(
            file_id="upload://sess_owner/pic.png_1700000000000",
            session_id="sess_other",
        )
    )

    assert response.path == str(stored)


def test_upload_content_missing_file_is_404(monkeypatch, tmp_path):
    _pin_workspace(monkeypatch, tmp_path)

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(
            file_controller.upload_content(
                file_id="upload://nope.png_1700000000000", session_id=None
            )
        )

    assert excinfo.value.status_code == 404
