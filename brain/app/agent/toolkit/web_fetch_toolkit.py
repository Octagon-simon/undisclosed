# ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========
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
# ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========

from typing import TYPE_CHECKING, Optional

from camel.toolkits import WebFetchToolkit as BaseWebFetchToolkit

if TYPE_CHECKING:
    from camel.agents import ChatAgent


class WebFetchToolkit(BaseWebFetchToolkit):
    """Fetch-and-analyze toolkit that reads streamed summaries correctly."""

    def _get_summary_agent(self) -> Optional["ChatAgent"]:
        # The brain streams every backend, and CAMEL's default
        # stream_accumulate=False leaves the last streamed response empty, so
        # the inherited summarizer returned "" for every page.
        agent = super()._get_summary_agent()
        if agent is not None:
            agent.stream_accumulate = True
            agent._stream_accumulate_explicit = True
        return agent

    def web_fetch_and_analyze(
        self, url: str, prompt: str, max_chars: int = 0
    ) -> str:
        result = super().web_fetch_and_analyze(url, prompt, max_chars)
        if not (result or "").strip():
            return (
                f"Error: fetched {url} but the summarizer returned no text. "
                "Retry with a smaller max_chars value."
            )
        return result
