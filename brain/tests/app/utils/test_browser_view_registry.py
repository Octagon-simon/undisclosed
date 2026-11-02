# Copyright (c) 2026 Simon Ugorji
# SPDX-License-Identifier: Apache-2.0

import pytest

from app.controller.browser_stream_controller import _select_page
from app.utils import browser_view_registry


@pytest.fixture(autouse=True)
def _clean_registry():
    browser_view_registry.clear()
    yield
    browser_view_registry.clear()


@pytest.mark.unit
def test_lookup_is_scoped_to_the_chat_port():
    browser_view_registry.remember_browser(
        "project-a", task_id="task-1", port=9223, session_id="aaaa"
    )
    browser_view_registry.remember_browser(
        "project-b", task_id="task-2", port=9224, session_id="bbbb"
    )

    assert (
        browser_view_registry.lookup_browser("project-a", "task-1")["port"]
        == 9223
    )
    assert (
        browser_view_registry.lookup_browser("project-b", "task-2")["port"]
        == 9224
    )


@pytest.mark.unit
def test_lookup_falls_back_to_the_projects_latest_task():
    browser_view_registry.remember_browser(
        "project-a", task_id="old", port=9223
    )
    browser_view_registry.remember_browser(
        "project-a", task_id="new", port=9223, target_id="TAB-2"
    )

    # A task that never resolved a browser still finds its project's browser.
    entry = browser_view_registry.lookup_browser("project-a", "unknown")
    assert entry["port"] == 9223
    assert entry["target_id"] == "TAB-2"


@pytest.mark.unit
def test_remember_merges_fields_instead_of_replacing():
    browser_view_registry.remember_browser(
        "project-a", task_id="task-1", port=9223, session_id="aaaa"
    )
    browser_view_registry.remember_browser(
        "project-a", task_id="task-1", target_id="TAB-9", url="https://x.test"
    )

    entry = browser_view_registry.lookup_browser("project-a", "task-1")
    assert entry["port"] == 9223
    assert entry["session_id"] == "aaaa"
    assert entry["target_id"] == "TAB-9"
    assert entry["url"] == "https://x.test"


@pytest.mark.unit
def test_lookup_without_a_project_returns_none():
    assert browser_view_registry.lookup_browser(None) is None
    assert browser_view_registry.lookup_browser("") is None


def _page(target_id, url):
    return {
        "id": target_id,
        "url": url,
        "type": "page",
        "webSocketDebuggerUrl": f"ws://localhost:9222/devtools/page/{target_id}",
    }


@pytest.mark.unit
def test_select_page_prefers_the_chats_last_tab():
    pages = [
        _page("USER-TAB", "https://mail.test"),
        _page("CHAT-TAB", "https://app.test"),
    ]

    chosen = _select_page(pages, preferred_target_id="CHAT-TAB")
    assert chosen["id"] == "CHAT-TAB"


@pytest.mark.unit
def test_select_page_follows_the_session_sentinel_even_when_blank():
    pages = [
        _page("USER-TAB", "https://mail.test"),
        _page("CHAT-TAB", "about:blank#eigent-session-7"),
    ]

    chosen = _select_page(pages, sentinel_session="session-7")
    assert chosen["id"] == "CHAT-TAB"


@pytest.mark.unit
def test_select_page_matches_the_last_navigated_url():
    pages = [
        _page("OTHER-CHAT", "https://other.test/"),
        _page("CHAT-TAB", "https://app.test"),
    ]

    chosen = _select_page(pages, preferred_url="https://app.test")
    assert chosen["id"] == "CHAT-TAB"


@pytest.mark.unit
def test_select_page_falls_back_to_a_real_page():
    pages = [
        _page("BLANK", "about:blank"),
        _page("REAL", "https://app.test"),
    ]

    assert _select_page(pages)["id"] == "REAL"
