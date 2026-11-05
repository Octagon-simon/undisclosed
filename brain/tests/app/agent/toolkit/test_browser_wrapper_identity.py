# Copyright (c) 2026 Simon Ugorji
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""A browser visit must record the chat that drove it, not crash on missing ids."""

from unittest.mock import AsyncMock, patch

import pytest

from app.agent.toolkit.hybrid_browser_toolkit import (
    HybridBrowserToolkit,
    WebSocketBrowserWrapper,
)


def _wrapper() -> WebSocketBrowserWrapper:
    return WebSocketBrowserWrapper({"browser_log_to_file": False})


@pytest.mark.unit
class TestWrapperChatIdentity:
    def test_remember_before_binding_is_a_no_op(self):
        wrapper = _wrapper()
        assert wrapper.api_task_id is None
        assert wrapper._chat_task_id is None
        wrapper._remember_tab_url("https://example.com")

    def test_remember_uses_bound_project_and_task(self):
        wrapper = _wrapper()
        wrapper.api_task_id = "project-1"
        wrapper._chat_task_id = "task-1"
        with patch(
            "app.agent.toolkit.hybrid_browser_toolkit.remember_browser"
        ) as remember:
            wrapper._remember_tab_url("https://example.com")

        remember.assert_called_once_with(
            "project-1",
            task_id="task-1",
            url="https://example.com",
        )


@pytest.mark.unit
class TestToolkitBindsWrapperIdentity:
    @pytest.mark.asyncio
    async def test_pooled_wrapper_is_bound_to_the_calling_chat(self):
        toolkit = object.__new__(HybridBrowserToolkit)
        toolkit.api_task_id = "project-1"
        toolkit._chat_task_id = "task-1"
        toolkit._ws_config = {
            "cdpUrl": "http://127.0.0.1:9222",
            "session_id": "session-1",
        }
        toolkit._ws_wrapper = None

        pooled = _wrapper()
        pooled.websocket = object()

        with (
            patch.object(
                toolkit,
                "_ensure_reachable_cdp_endpoint",
                new=AsyncMock(return_value="http://127.0.0.1:9222"),
            ),
            patch.object(
                toolkit, "_should_prime_shared_cdp_tab", return_value=False
            ),
            patch(
                "app.agent.toolkit.hybrid_browser_toolkit.websocket_connection_pool"
            ) as pool,
        ):
            pool.get_connection = AsyncMock(return_value=pooled)
            await toolkit._ensure_ws_wrapper()

        assert pooled.api_task_id == "project-1"
        assert pooled._chat_task_id == "task-1"
