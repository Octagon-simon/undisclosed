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

import logging
from typing import Any, Optional

from camel.toolkits import SlackToolkit as BaseSlackToolkit
from camel.toolkits.function_tool import FunctionTool

from app.agent.toolkit.abstract_toolkit import AbstractToolkit
from app.component.environment import env
from app.service.task import Agents
from app.utils.listen.toolkit_listen import auto_listen_toolkit

logger = logging.getLogger("slack_toolkit")


def _slack_response_field(response: Any, key: str) -> Optional[str]:
    """Read a field from a SlackResponse without assuming its interface.

    Module-level (not a method): the toolkit base wraps declared methods, so a
    `@staticmethod` here would be called as a bound method and blow up with
    "takes 2 positional arguments but 3 were given".
    """
    if response is None:
        return None
    for getter in (
        lambda: response.get(key),
        lambda: response[key],
        lambda: response.data.get(key),
    ):
        try:
            value = getter()
        except Exception:
            continue
        if value:
            return str(value)
    return None


@auto_listen_toolkit(BaseSlackToolkit)
class SlackToolkit(BaseSlackToolkit, AbstractToolkit):
    agent_name: str = Agents.social_media_agent

    def __init__(self, api_task_id: str, timeout: float | None = None):
        super().__init__(timeout)
        self.api_task_id = api_task_id

    @classmethod
    def get_can_use_tools(cls, api_task_id: str) -> list[FunctionTool]:
        logger.debug(f"slack===={env('SLACK_BOT_TOKEN')}")
        if env("SLACK_BOT_TOKEN") or env("SLACK_USER_TOKEN"):
            return SlackToolkit(api_task_id).get_tools()
        else:
            return []

    def _record_thread_link(
        self, channel_id: str, response: Any, thread_ts: Optional[str]
    ) -> None:
        r"""Remember the conversation THIS run posted from, keyed by the Slack
        thread the post belongs to.

        A workspace-scoped trigger creates a new conversation every run, so a
        reply-trigger cannot know the conversation ahead of time. The Slack
        thread is the stable handle: a reply arrives on the same thread and
        resolves back to the conversation that opened it. Best-effort only; a
        failure here must never break sending the message.
        """
        try:
            posted_ts = _slack_response_field(response, "ts")
            post_channel = _slack_response_field(response, "channel") or channel_id
            # The thread root: the explicit thread_ts when we replied into an
            # existing thread, otherwise the message's own ts (it opens one).
            root_ts = thread_ts or posted_ts
            if not post_channel or not root_ts:
                return
            from app.controller.trigger_controller import (
                record_slack_thread_link,
            )

            record_slack_thread_link(
                post_channel,
                root_ts,
                self.api_task_id,
                message_ts=posted_ts,
            )
        except Exception:
            logger.debug("failed to record slack thread link", exc_info=True)

    def send_slack_message(
        self,
        message: str,
        channel_id: str,
        file_path: Optional[str] = None,
        user: Optional[str] = None,
        thread_ts: Optional[str] = None,
    ) -> str:
        r"""Send a message to a Slack channel. When use this function you must
        call `get_slack_channel_information` function first to get the
        `channel id`. If use user, you must use `get_slack_user_list`
        function first to get the user id.

        Args:
            message (str): The message to send.
            channel_id (str): The ID of the channel to send the message to.
            file_path (Optional[str]): The local path of a file to upload
                with the message.
            user (Optional[str]): The ID of a user to send an ephemeral
                message to (visible only to that user).
            thread_ts (Optional[str]): The `ts` of a parent message to post
                this as a threaded reply. Omit to post a new top-level message.

        Returns:
            str: A confirmation message indicating success or an error
                message.
        """
        from slack_sdk.errors import SlackApiError

        try:
            slack_client = self._login_slack()
            if file_path:
                response = slack_client.files_upload_v2(
                    channel=channel_id,
                    file=file_path,
                    initial_comment=message,
                )
                return f"File sent successfully, got response: {response}"
            if user:
                response = slack_client.chat_postEphemeral(
                    channel=channel_id, text=message, user=user
                )
            else:
                post_kwargs: dict[str, Any] = {
                    "channel": channel_id,
                    "text": message,
                }
                if thread_ts:
                    post_kwargs["thread_ts"] = thread_ts
                response = slack_client.chat_postMessage(**post_kwargs)
                # Link this thread to the conversation this run belongs to, so a
                # reply on the thread can follow up in the same conversation.
                self._record_thread_link(channel_id, response, thread_ts)
            return (
                f"Message: {message} sent successfully, "
                f"got response: {response}"
            )
        except SlackApiError as e:
            return f"Error sending message: {e.response['error']}"
