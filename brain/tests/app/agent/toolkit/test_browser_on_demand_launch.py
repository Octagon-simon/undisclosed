# Copyright (c) 2026 Simon Ugorji
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""On-demand browser launch: a browser starts on the first browser action,
not at the start of every turn."""

import os
from unittest.mock import patch

import pytest

from app.agent.toolkit.hybrid_browser_toolkit import HybridBrowserToolkit
from app.utils.browser_launcher import launch_local_cdp_browser


def _toolkit(cdp_url: str) -> HybridBrowserToolkit:
    toolkit = object.__new__(HybridBrowserToolkit)
    toolkit.api_task_id = "test-task"
    toolkit._ws_config = {"cdpUrl": cdp_url, "session_id": "test"}
    toolkit._cdp_endpoint_checked = False
    toolkit._launch_attempted = False
    return toolkit


@pytest.mark.unit
class TestLaunchLocalCdpBrowser:
    def test_skips_remote_endpoint(self):
        with patch(
            "app.utils.browser_launcher.ensure_cdp_browser_endpoint"
        ) as mock_ensure:
            assert launch_local_cdp_browser("http://worker-17:9222") is None
            mock_ensure.assert_not_called()

    def test_skips_when_auto_launch_disabled(self):
        with (
            patch.dict(
                os.environ,
                {"UNDISCLOSED_BRAIN_LAUNCH_BROWSER": "0"},
                clear=True,
            ),
            patch(
                "app.utils.browser_launcher.ensure_cdp_browser_endpoint"
            ) as mock_ensure,
        ):
            assert launch_local_cdp_browser("http://127.0.0.1:9222") is None
            mock_ensure.assert_not_called()

    def test_launches_on_local_endpoint(self):
        with patch(
            "app.utils.browser_launcher.ensure_cdp_browser_endpoint",
            return_value="http://127.0.0.1:9231",
        ) as mock_ensure:
            assert (
                launch_local_cdp_browser("http://127.0.0.1:9222")
                == "http://127.0.0.1:9231"
            )
            mock_ensure.assert_called_once_with(9222)


@pytest.mark.unit
class TestToolkitOnDemandLaunch:
    @pytest.mark.asyncio
    async def test_reachable_endpoint_is_untouched(self):
        toolkit = _toolkit("http://127.0.0.1:9222")
        with (
            patch(
                "app.agent.toolkit.hybrid_browser_toolkit.is_cdp_url_available",
                return_value=True,
            ),
            patch(
                "app.agent.toolkit.hybrid_browser_toolkit.launch_local_cdp_browser"
            ) as mock_launch,
        ):
            endpoint = await toolkit._ensure_reachable_cdp_endpoint(
                toolkit._ws_cdp_url()
            )

            assert endpoint == "http://127.0.0.1:9222"
            mock_launch.assert_not_called()

    @pytest.mark.asyncio
    async def test_remote_endpoint_never_launches(self):
        toolkit = _toolkit("http://worker-17:9222")
        with (
            patch(
                "app.agent.toolkit.hybrid_browser_toolkit.is_cdp_url_available",
                return_value=False,
            ),
            patch(
                "app.agent.toolkit.hybrid_browser_toolkit.launch_local_cdp_browser"
            ) as mock_launch,
        ):
            endpoint = await toolkit._ensure_reachable_cdp_endpoint(
                toolkit._ws_cdp_url()
            )

            assert endpoint == "http://worker-17:9222"
            mock_launch.assert_not_called()

    @pytest.mark.asyncio
    async def test_launches_once_and_updates_config(self):
        toolkit = _toolkit("http://127.0.0.1:9222")
        with (
            patch(
                "app.agent.toolkit.hybrid_browser_toolkit.is_cdp_url_available",
                return_value=False,
            ),
            patch(
                "app.agent.toolkit.hybrid_browser_toolkit.launch_local_cdp_browser",
                return_value="http://127.0.0.1:9231",
            ) as mock_launch,
        ):
            endpoint = await toolkit._ensure_reachable_cdp_endpoint(
                toolkit._ws_cdp_url()
            )
            assert endpoint == "http://127.0.0.1:9231"
            assert toolkit._ws_cdp_url() == "http://127.0.0.1:9231"

            # Later tool calls use the new endpoint and do not launch again.
            again = await toolkit._ensure_reachable_cdp_endpoint(
                toolkit._ws_cdp_url()
            )
            assert again == "http://127.0.0.1:9231"
            mock_launch.assert_called_once()

    @pytest.mark.asyncio
    async def test_another_toolkit_launch_is_reused(self):
        toolkit = _toolkit("http://127.0.0.1:9222")
        with (
            patch(
                "app.agent.toolkit.hybrid_browser_toolkit.is_cdp_url_available",
                side_effect=[False, True],
            ),
            patch(
                "app.agent.toolkit.hybrid_browser_toolkit.launch_local_cdp_browser"
            ) as mock_launch,
        ):
            endpoint = await toolkit._ensure_reachable_cdp_endpoint(
                toolkit._ws_cdp_url()
            )

            assert endpoint == "http://127.0.0.1:9222"
            mock_launch.assert_not_called()

    @pytest.mark.asyncio
    async def test_launch_attempted_flag_skips_new_launch(self):
        toolkit = _toolkit("http://127.0.0.1:9222")
        toolkit._launch_attempted = True
        with (
            patch(
                "app.agent.toolkit.hybrid_browser_toolkit.is_cdp_url_available",
                return_value=False,
            ),
            patch(
                "app.agent.toolkit.hybrid_browser_toolkit.launch_local_cdp_browser"
            ) as mock_launch,
        ):
            assert (
                await toolkit._ensure_reachable_cdp_endpoint(
                    toolkit._ws_cdp_url()
                )
                == "http://127.0.0.1:9222"
            )
            mock_launch.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_launch_is_not_retried(self):
        toolkit = _toolkit("http://127.0.0.1:9222")
        with (
            patch(
                "app.agent.toolkit.hybrid_browser_toolkit.is_cdp_url_available",
                return_value=False,
            ),
            patch(
                "app.agent.toolkit.hybrid_browser_toolkit.launch_local_cdp_browser",
                return_value=None,
            ) as mock_launch,
        ):
            assert (
                await toolkit._ensure_reachable_cdp_endpoint(
                    toolkit._ws_cdp_url()
                )
                == "http://127.0.0.1:9222"
            )
            assert (
                await toolkit._ensure_reachable_cdp_endpoint(
                    toolkit._ws_cdp_url()
                )
                == "http://127.0.0.1:9222"
            )
            mock_launch.assert_called_once()
