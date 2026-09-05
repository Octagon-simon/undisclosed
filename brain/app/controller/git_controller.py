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

"""AI git helpers for the editor. `POST /git/commit-message` turns a staged diff
into a clean Conventional-Commits message, using the SAME model the user is
chatting with (cached in agent_model) — so the Source Control 'generate message'
button costs nothing extra to set up."""

import logging

from fastapi import APIRouter, HTTPException

from app.agent.agent_model import get_last_model

router = APIRouter()
logger = logging.getLogger("git_controller")

_COMMIT_SYS = """You write ONE Git commit message from a staged diff.

Rules:
- Conventional Commits: `type(scope): subject`. Types: feat, fix, chore,
  refactor, docs, test, perf, style, build, ci. Scope is optional.
- Subject: imperative mood, <= 72 chars, no trailing period.
- For non-trivial changes, add a blank line then a concise body (a few bullet
  points on WHAT and WHY). Skip the body for tiny changes.
- Output ONLY the commit message text — no backticks, no preamble, no
  explanation, no surrounding quotes."""


@router.post("/git/commit-message")
async def git_commit_message(body: dict) -> dict:
    """Body: { diff }. Returns { success, message }."""
    diff = ((body or {}).get("diff") or "").strip()
    if not diff:
        raise HTTPException(status_code=400, detail="diff is required")

    model = get_last_model()
    if model is None:
        return {
            "success": False,
            "message": "No model is loaded yet — send one message to the agent "
            "so it knows which model to use, then try again.",
        }

    # Keep the call cheap: a very large diff is truncated (the head carries the
    # most signal for a summary).
    if len(diff) > 20000:
        diff = diff[:20000] + "\n…(diff truncated)…"

    try:
        from camel.agents import ChatAgent
        from camel.messages import BaseMessage

        agent = ChatAgent(
            BaseMessage.make_assistant_message(
                role_name="Committer", content=_COMMIT_SYS
            ),
            model=model,
        )
        response = await agent.astep(
            f"Write a commit message for this staged diff:\n\n{diff}"
        )
        message = ""
        try:
            # get_last_model() reuses whatever the chat is on — which may be a
            # STREAMING model (single-agent runs with stream=True) and/or carry a
            # `thinking` config. A streaming response has no `.msg` until drained,
            # so handle both: drain content chunks if streaming, else read .msg.
            from camel.agents.chat_agent import AsyncStreamingChatAgentResponse

            if isinstance(response, AsyncStreamingChatAgentResponse):
                async for chunk in response:
                    c = getattr(getattr(chunk, "msg", None), "content", "")
                    if c:
                        message += c
            else:
                message = getattr(response.msg, "content", "") or ""
            message = message.strip()
        except Exception:
            message = ""
        # Strip accidental code fences / surrounding quotes.
        message = message.strip("`").strip().strip('"').strip()
        if not message:
            return {"success": False, "message": "The model returned nothing."}
        return {"success": True, "message": message}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "commit-message generation failed: %s", exc, exc_info=True
        )
        return {"success": False, "message": f"Failed to generate: {exc}"}
