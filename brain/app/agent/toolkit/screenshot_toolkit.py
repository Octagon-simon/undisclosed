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

import os
import sys
from pathlib import Path

from camel.agents import ChatAgent
from camel.messages import BaseMessage
from camel.toolkits import ScreenshotToolkit as BaseScreenshotToolkit
from PIL import Image

from app.agent.listen_chat_agent import default_step_timeout
from app.agent.toolkit.abstract_toolkit import AbstractToolkit
from app.component.environment import env
from app.utils.listen.toolkit_listen import auto_listen_toolkit
from app.utils.vision_backend import vision_backend_for


@auto_listen_toolkit(BaseScreenshotToolkit)
class ScreenshotToolkit(BaseScreenshotToolkit, AbstractToolkit):
    agent_name: str

    @classmethod
    def toolkit_name(cls) -> str:
        # "Screenshot Toolkit" made the model pick this instead of Page
        # Screenshots for a live URL. This toolkit reads images; name it that.
        return "Image Reader"

    def __init__(
        self,
        api_task_id,
        agent_name: str,
        working_directory: str | None = None,
        timeout: float | None = None,
        enable_desktop_capture: bool = True,
    ):
        self.api_task_id = api_task_id
        self.agent_name = agent_name
        self.enable_desktop_capture = enable_desktop_capture
        if working_directory is None:
            working_directory = env(
                "file_save_path", os.path.expanduser("~/Downloads")
            )
        super().__init__(working_directory, timeout)

    def read_image(
        self,
        image_path: str,
        instruction: str = "",
    ) -> str:
        """Read and analyze an image file that already exists on disk.

        Use this for a saved PNG/JPG/WebP: a diagram, a previous screenshot,
        a chart the task produced. It captures nothing. For a live web page
        load Page Screenshots and call `capture_page`; to capture the user's
        desktop screen call `take_screenshot_and_read_image`.

        Args:
            image_path (str): Path to the image file.
            instruction (str, optional): What to look for in the image.

        Returns:
            str: The vision model's answer, or an error message.
        """
        if self.agent is None:
            return (
                "Error: No agent registered. Please pass this toolkit to "
                "ChatAgent via toolkits_to_register_agent parameter."
            )

        try:
            image_path = str(Path(image_path).absolute())
            if not os.path.exists(image_path):
                return f"Error: Screenshot file not found: {image_path}"

            backend = vision_backend_for(self.agent)
            if backend is None:
                return (
                    "Error: no vision-capable model is configured. Add one "
                    "under Agents > Models (or set UNDISCLOSED_VISION_MODEL)."
                )

            img = Image.open(image_path)
            message = BaseMessage.make_user_message(
                role_name="User",
                content=instruction,
                image_list=[img],
            )

            #a nested self.agent.step() here corrupts the caller's tool-call memory
            vision_agent = ChatAgent(
                system_message=(
                    "You are a careful visual assistant. Answer only from the "
                    "provided image and user instruction."
                ),
                model=backend,
                tools=[],
                toolkits_to_register_agent=None,
                external_tools=None,
                step_timeout=getattr(
                    self.agent, "step_timeout", default_step_timeout()
                ),
            )
            response = vision_agent.step(message)
            if getattr(response, "msg", None) is not None:
                return response.msg.content
            if getattr(response, "msgs", None):
                return response.msgs[0].content
            return "Error reading screenshot: empty response"
        except Exception as e:
            return f"Error reading screenshot: {e}"

    def take_screenshot_and_read_image(
        self,
        filename: str,
        save_to_file: bool = True,
        read_image: bool = True,
        instruction: str | None = None,
    ) -> str:
        """Capture the user's entire desktop screen, then optionally read it.

        Use this only when the task is about what is on the user's screen right
        now. It is not a page camera: for a URL load Page Screenshots and call
        `capture_page` instead.

        Args:
            filename (str): File name to save the capture as.
            save_to_file (bool): Save the capture to disk. Default True.
            read_image (bool): Analyze the capture with the vision model.
            instruction (str, optional): What to look for in the capture.

        Returns:
            str: Capture status, plus the vision answer when requested.
        """
        if not self.enable_desktop_capture:
            return (
                "Error: Desktop screenshot capture is disabled for this agent. "
                "Use read_image with an existing image file path instead."
            )

        result = super().take_screenshot_and_read_image(
            filename=filename,
            save_to_file=save_to_file,
            read_image=read_image,
            instruction=instruction,
        )
        if result.startswith("Error taking screenshot:") and sys.platform == "darwin":
            result += (
                " macOS blocks screen capture until the app hosting the brain "
                "has Screen Recording permission (System Settings > Privacy & "
                "Security > Screen Recording)."
            )
        return result

    def get_tools(self):
        tools = super().get_tools()
        if self.enable_desktop_capture:
            return tools

        return [
            tool for tool in tools if tool.get_function_name() == "read_image"
        ]
