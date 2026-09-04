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
import logging
import os
from typing import Any

from camel.agents import ChatAgent
from camel.agents.chat_agent import AsyncStreamingChatAgentResponse
from camel.messages import BaseMessage
from camel.responses import ChatAgentResponse
from camel.types import OpenAIBackendRole
from fastapi import Request

from app.agent.factory.single_agent import single_agent
from app.hands.interface import IHands
from app.hooks.emitters import (
    emit_session_paused,
    emit_session_resumed,
    emit_task_cancelled,
    emit_task_completed,
    emit_task_failed,
    emit_task_started,
)
from app.memory import (
    build_durable_context_for_task_lock,
    finalize_task_lock_run_memory,
)
from app.model.chat import Chat, sse_json
from app.agent.tool_rag import (
    reconcile_agent_tools,
    reconcile_agent_tools_routed,
)
from app.component.environment import env
from app.utils.file_utils import resolve_attach_refs, resolve_upload_ref
from app.utils.model_capabilities import model_supports_vision
from app.model.enums import Status
from app.service.approval_manager import ApprovalManager
from app.service.task import (
    Action,
    ActionData,
    ActionImproveData,
    ImprovePayload,
    TaskLock,
    delete_task_lock,
    set_current_task_id,
)
from app.utils.agent_memory import (
    build_memory_context,
    record_agent_memory_snapshot,
)
from app.utils.file_utils import get_working_directory

logger = logging.getLogger("single_agent_service")


def _fire_hook(coro) -> None:
    """Schedule a hook emitter without letting it fail or delay the loop.

    Hooks are strictly best-effort: a slow or broken external command runs on
    its own task and is never awaited by the SSE generator. Exceptions are
    logged at debug level inside app.hooks; this callback only guards against
    scheduling-time errors and keeps 'task exception was never retrieved'
    noise out of the logs.
    """

    def _swallow(task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("Hook emitter raised", exc_info=True)

    try:
        task = asyncio.create_task(coro)
    except RuntimeError:
        # No running loop (should not happen on this code path); drop quietly.
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return
    task.add_done_callback(_swallow)


# Char budget for the durable memory bundle (~32k chars at 4 chars/token).
# Override via UNDISCLOSED_MEMORY_TOKEN_BUDGET if you need to tune in the field.
try:
    _MEMORY_TOKEN_BUDGET = int(
        os.environ.get("UNDISCLOSED_MEMORY_TOKEN_BUDGET", "8000")
    )
except ValueError:
    _MEMORY_TOKEN_BUDGET = 8000


def _apply_model_override(options: Chat, payload: ImprovePayload) -> bool:
    """Apply a user-selected model override to options for a follow-up turn.

    Returns True when the model actually changed (so the caller knows to
    rebuild the cached agent), False when there is no override or it matches
    the current configuration.

    The frontend sends the full resolved model config on the improve request so
    a mid-conversation model switch is honored even though the conversation's
    project pin / history still references the original model.
    """
    if not payload.model_platform and not payload.model_type:
        # No override supplied on this turn.
        return False

    # "changed" reflects a change to the model identity (platform / type /
    # auth_source) which is what the cached agent was built from. Only these
    # force a rebuild. Credentials and extra config are still applied so a
    # custom/local provider switch propagates correctly, but they do not by
    # themselves invalidate the cached agent (e.g. sending `{}` where the
    # current config is `None` should not trigger a pointless rebuild).
    changed = False

    if (
        payload.model_platform
        and payload.model_platform != options.model_platform
    ):
        options.model_platform = payload.model_platform
        changed = True
    if payload.model_type and payload.model_type != options.model_type:
        options.model_type = payload.model_type
        changed = True
    if (
        getattr(options, "auth_source", None) != payload.auth_source
        and payload.auth_source is not None
    ):
        options.auth_source = payload.auth_source
        changed = True

    if payload.api_key is not None and payload.api_key != options.api_key:
        options.api_key = payload.api_key
    if payload.api_url is not None and payload.api_url != options.api_url:
        options.api_url = payload.api_url
    if payload.model_config_dict is not None:
        # Avoid treating a populated config replacing an empty one as no-op.
        options.model_config_dict = payload.model_config_dict
    if payload.extra_params is not None:
        options.extra_params = payload.extra_params

    if changed:
        logger.info(
            "Model override applied for follow-up turn",
            extra={
                "project_id": options.project_id,
                "model_platform": options.model_platform,
                "model_type": options.model_type,
                "auth_source": getattr(options, "auth_source", None),
            },
        )
    return changed


def _memory_enabled(options: Chat) -> bool:
    """Whether semantic memory is on for this run (toolkit_config.memory.enabled,
    default True) — mirrors how governance mode is read from toolkit_config."""
    cfg = (options.toolkit_config or {}).get("memory")
    if isinstance(cfg, dict) and "enabled" in cfg:
        return bool(cfg["enabled"])
    return True


def _thinking_enabled(options: Chat) -> bool:
    """Whether to surface the model's reasoning in a thinking block
    (toolkit_config.thinking.enabled, default True)."""
    cfg = (options.toolkit_config or {}).get("thinking")
    if isinstance(cfg, dict) and "enabled" in cfg:
        return bool(cfg["enabled"])
    return True


# Minimum length for a reasoning payload to be treated as a real "thinking
# process" worth surfacing. Non-reasoning models sometimes drop a trivial echo
# (e.g. the user typed "Hii" and reasoning_content comes back "Hii") into the
# thinking block; those are noise, not thought.
_MIN_MEANINGFUL_REASONING_LEN = 40


def _is_meaningful_reasoning(reasoning: str, final_result: str) -> bool:
    """True when ``reasoning`` looks like genuine model thinking rather than a
    trivial echo of the user's input or a restatement of the final answer."""
    r = (reasoning or "").strip()
    if len(r) < _MIN_MEANINGFUL_REASONING_LEN:
        return False
    fr = (final_result or "").strip()
    if fr and (r == fr or r in fr or fr in r):
        return False
    return True


def _build_single_agent_context(
    task_lock: TaskLock,
    project_context: str | None = None,
    current_user_prompt: str = "",
    memory_enabled: bool = True,
) -> str:
    # 1. Durable cross-restart context from LocalMemoryStore (M4 path).
    durable = build_durable_context_for_task_lock(
        task_lock,
        mode="single_agent",
        current_user_prompt=current_user_prompt,
        token_budget=_MEMORY_TOKEN_BUDGET,
        include_semantic=memory_enabled,
    )
    if durable:
        return durable + "\n\n"

    # 2. In-process conversation history (hot follow-up turns). Only the MOST
    #    RECENT turns are injected — dumping the whole history would re-saturate
    #    the freshly-reset memory and re-trigger the verbatim-repeat loop. Older
    #    details are retrievable on demand via the recall_conversation tool.
    if getattr(task_lock, "conversation_history", None):
        _recent_history = list(task_lock.conversation_history)[-6:]
        lines = [
            "=== Recent messages in this conversation (background only, NOT the "
            "current request; for anything older call recall_conversation) ==="
        ]
        for entry in _recent_history:
            role = entry.get("role", "")
            content = entry.get("content", "")
            if role == "task_result" and isinstance(content, dict):
                task_content = content.get("task_content")
                task_result = content.get("task_result")
                if task_content:
                    lines.append(f"Previous task: {task_content}")
                if task_result:
                    lines.append(f"Previous result: {task_result}")
            elif content:
                lines.append(f"{role}: {content}")
        memory_context = build_memory_context(task_lock)
        if memory_context:
            lines.append(memory_context.rstrip())
        lines.append("=== End earlier conversation ===")
        return "\n".join(lines) + "\n\n"

    # 3. Phase-0 bridge fallback (frontend-sent project_context).
    durable_context = (project_context or "").strip()
    if not durable_context:
        return ""
    return (
        "=== Persisted Project Context ===\n"
        f"{durable_context}\n"
        "=== End Persisted Project Context ===\n\n"
    )


def _finalize_memory_for_turn(
    task_lock: TaskLock,
    *,
    state: str,
    final_result: str | None = None,
    error: str | None = None,
) -> None:
    """Best-effort end-of-run memory write."""

    finalize_task_lock_run_memory(
        task_lock,
        state=state,  # type: ignore[arg-type]
        final_result=final_result,
        error=error,
    )


def _format_active_editor(active_editor: dict | None) -> str:
    """One-line note about the file the user is looking at, for the agent's
    background context. Empty when there's no active editor."""
    if not isinstance(active_editor, dict):
        return ""
    path = str(active_editor.get("path") or "").strip()
    if not path:
        return ""
    lang = str(active_editor.get("languageId") or "").strip()
    sel = active_editor.get("selection") or {}
    lines = ""
    if isinstance(sel, dict) and sel.get("startLine") and sel.get("endLine"):
        lines = f", lines {sel['startLine']}-{sel['endLine']}"
    lang_part = f", language: {lang}" if lang else ""
    return (
        f"The user currently has `{path}`{lang_part}{lines} open in the editor. "
        "Treat this as their likely focus unless they say otherwise."
    )


def _build_single_agent_prompt(
    task_lock: TaskLock,
    question: str,
    attaches: list[str],
    project_context: str | None = None,
    vision_capable: bool = True,
    memory_enabled: bool = True,
    is_fresh_agent: bool = True,
    active_editor: dict | None = None,
) -> tuple[str, str]:
    """Return (clean_user_prompt, background_context).

    The user prompt is JUST the current message plus any attachments — nothing
    else, so it never leaks the scaffold into the UI and the model responds to
    exactly what the user typed. The background context (recalled facts + earlier
    turns, only for a fresh agent) is returned separately; the caller injects it
    as a SYSTEM memory record so it stays background instead of competing with
    the current message.
    """
    if is_fresh_agent:
        context = _build_single_agent_context(
            task_lock,
            project_context,
            current_user_prompt=question,
            memory_enabled=memory_enabled,
        )
    else:
        context = ""

    # Live editor context applies to EVERY turn (not just a fresh agent): it's
    # ephemeral "what am I looking at now" state, refreshed each message.
    editor_note = _format_active_editor(active_editor)
    if editor_note:
        context = f"{context}\n\n{editor_note}".strip() if context else editor_note

    attachment_context = ""
    if attaches:
        # Resolve upload:// refs to absolute paths so the agent's file/shell
        # tools can actually open them (raw upload:// refs aren't real paths).
        resolved = resolve_attach_refs(attaches)
        attachment_context = "Attachments:\n" + "\n".join(
            f"- {path}" for path in resolved
        )
        # When the model can't natively see images, tell it to read them via
        # tools (e.g. OCR) rather than assuming it can view them directly.
        if not vision_capable and any(
            _is_image_path(p) for p in resolved
        ):
            attachment_context += (
                "\n\nNote: your model cannot view images directly. For any "
                "image attachment, extract its content using available tools "
                "(e.g. an OCR/vision tool or reading the file), then proceed."
            )
        attachment_context += "\n\n"

    prompt = f"{attachment_context}{question}"
    return prompt, context


def _is_image_path(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in _IMAGE_EXTENSIONS


_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".avif",
}


_IMAGE_OMITTED_MARKER = "[Image omitted to save context"

_CAPTION_INSTRUCTION = (
    "Describe this image in 2-4 sentences so it can be referenced later in the "
    "conversation WITHOUT seeing the image again. Capture the main subject, and "
    "transcribe any important visible text, numbers, labels, or UI details. Be "
    "specific and factual; do not add commentary."
)


async def _caption_images(agent: Any, images: list[Any]) -> str | None:
    """Produce a concise text description of the given images using the agent's
    own model, so the description can replace the raw image in memory. Returns
    None on any failure (caller falls back to a generic marker).
    """
    if not images:
        return None
    try:
        message = BaseMessage.make_user_message(
            role_name="User",
            content=_CAPTION_INSTRUCTION,
            image_list=images,
        )
        vision_agent = ChatAgent(
            system_message=(
                "You are a careful visual assistant. Describe only what is "
                "actually visible in the image."
            ),
            model=agent.model_backend,
            tools=[],
        )
        response = await vision_agent.astep(message)
        msg = getattr(response, "msg", None)
        if msg is not None and getattr(msg, "content", None):
            return msg.content.strip()
        msgs = getattr(response, "msgs", None)
        if msgs:
            return msgs[0].content.strip()
    except Exception:
        logger.warning("Failed to caption image for memory collapse", exc_info=True)
    return None


async def _collapse_memory_images(agent: Any) -> None:
    """Replace raw images in the agent's stored memory with a text description.

    An image attach is sent to the model as a vision block on the turn it is
    added (so the model sees it once). Left in memory, it would be re-sent —
    re-encoded and re-billed — on EVERY subsequent turn. This rewrites prior
    image messages to a text caption (a real description of the image, so the
    content isn't lost) so only the newest turn's image carries pixels.
    Best-effort: any failure leaves that record untouched.
    """
    import dataclasses

    memory = getattr(agent, "memory", None)
    if memory is None:
        return
    try:
        context_records = memory.retrieve()
    except Exception:
        return

    new_records = []
    changed = False
    for ctx in context_records:
        record = getattr(ctx, "memory_record", None)
        if record is None:
            continue
        message = getattr(record, "message", None)
        images = getattr(message, "image_list", None) if message else None
        if images:
            caption = await _caption_images(agent, list(images))
            count = len(images)
            if caption:
                note = (
                    f"{_IMAGE_OMITTED_MARKER}. Description of the "
                    f"{'image' if count == 1 else f'{count} images'} "
                    f"attached here: {caption}]"
                )
            else:
                note = (
                    f"{_IMAGE_OMITTED_MARKER}: {count} image(s) shown and "
                    "described earlier in this conversation.]"
                )
            base = message.content or ""
            base = f"{base}\n\n{note}" if base else note
            try:
                new_message = dataclasses.replace(
                    message, image_list=None, content=base
                )
                new_record = record.model_copy(
                    update={"message": new_message}
                )
            except Exception:
                logger.warning(
                    "Failed to collapse an image memory record",
                    exc_info=True,
                )
                new_records.append(record)
                continue
            new_records.append(new_record)
            changed = True
        else:
            new_records.append(record)

    if not changed:
        return
    try:
        memory.clear()
        memory.write_records(new_records)
    except Exception:
        logger.warning("Failed to rewrite memory after image collapse", exc_info=True)


def _load_attach_images(attaches: list[str]) -> list[Any]:
    """Open image attachments as PIL images so they can be attached to the
    user message (`image_list`) and actually SEEN by a multimodal model.

    Attaches arrive as upload:// refs or paths; resolve each, keep ones with an
    image extension, and open them. Non-images and unreadable files are skipped.
    Returns [] when Pillow isn't available or nothing loads.
    """
    if not attaches:
        return []
    try:
        from PIL import Image
    except Exception:
        return []
    images: list[Any] = []
    for ref in attaches:
        resolved = resolve_upload_ref(ref)
        ext = os.path.splitext(resolved)[1].lower()
        if ext not in _IMAGE_EXTENSIONS:
            continue
        try:
            if not os.path.isfile(resolved):
                continue
            img = Image.open(resolved)
            img.load()
            images.append(img)
        except Exception:
            logger.warning(
                "Failed to open image attachment %r", resolved, exc_info=True
            )
    return images


async def _response_content(
    response: ChatAgentResponse | AsyncStreamingChatAgentResponse,
) -> tuple[str, int, str]:
    def extract_tokens(response_chunk: Any) -> int:
        if response_chunk is None:
            return 0
        info = getattr(response_chunk, "info", None) or {}
        usage_info = info.get("usage") or info.get("token_usage") or {}
        return int(usage_info.get("total_tokens", 0) or 0)

    def reasoning_of(msg: Any) -> str:
        return str(getattr(msg, "reasoning_content", "") or "") if msg else ""

    if isinstance(response, AsyncStreamingChatAgentResponse):
        content = ""
        reasoning = ""
        last_chunk = None
        async for chunk in response:
            last_chunk = chunk
            if chunk.msg and chunk.msg.content:
                content += chunk.msg.content
        if last_chunk is not None:
            reasoning = reasoning_of(getattr(last_chunk, "msg", None))
        return content, extract_tokens(last_chunk), reasoning

    msg = getattr(response, "msg", None)
    usage_tokens = extract_tokens(response)
    reasoning = reasoning_of(msg)
    if msg is not None and getattr(msg, "content", None):
        return msg.content, usage_tokens, reasoning

    msgs = getattr(response, "msgs", None)
    if msgs:
        last = msgs[-1]
        return (
            getattr(last, "content", "") or "",
            usage_tokens,
            reasoning or reasoning_of(last),
        )

    return "", usage_tokens, reasoning


def _action_to_sse(item: ActionData) -> str | None:
    if item.action == Action.create_agent:
        return sse_json("create_agent", item.data)
    if item.action == Action.activate_agent:
        return sse_json("activate_agent", item.data)
    if item.action == Action.deactivate_agent:
        return sse_json("deactivate_agent", item.data)
    if item.action == Action.request_usage:
        return sse_json("request_usage", item.data)
    if item.action == Action.assign_task:
        return sse_json("assign_task", item.data)
    if item.action == Action.activate_toolkit:
        return sse_json("activate_toolkit", item.data)
    if item.action == Action.deactivate_toolkit:
        return sse_json("deactivate_toolkit", item.data)
    if item.action == Action.write_file:
        return sse_json(
            "write_file",
            {
                "file_path": item.data,
                "process_task_id": item.process_task_id,
            },
        )
    if item.action == Action.ask:
        return sse_json("ask", item.data)
    if item.action == Action.notice:
        return sse_json(
            "notice",
            {
                "notice": item.data,
                "process_task_id": item.process_task_id,
            },
        )
    if item.action == Action.terminal:
        return sse_json(
            "terminal",
            {
                "output": item.data,
                "process_task_id": item.process_task_id,
            },
        )
    if item.action == Action.todo_state:
        return sse_json("todo_state", item.data)
    if item.action == Action.approval_request:
        # Every other branch's `.data` is a plain dict/str; ApprovalRequestPayload
        # is a BaseModel, which `sse_json`'s bare `json.dumps` cannot serialize
        # on its own -- dump it to a dict first.
        return sse_json("approval_request", item.data.model_dump())
    if item.action == Action.approval_resolved:
        return sse_json("approval_resolved", item.data.model_dump())
    if item.action == Action.budget_not_enough:
        return sse_json(
            Action.budget_not_enough, {"message": "budget not enough"}
        )
    return None


def _inject_user_message_into_running_agent(agent: Any, question: str) -> bool:
    """Inject a mid-run user question into a live agent's memory.

    The agent is blocked inside an in-flight LLM request/tool loop, so the
    question cannot steer the current turn. Writing it into the agent's
    memory guarantees the model sees it on the very next step instead of the
    message being silently dropped. Best-effort: returns False when the
    agent has not been created yet or memory write fails.
    """
    if agent is None:
        return False
    try:
        agent.update_memory(
            BaseMessage.make_user_message(
                role_name="User",
                content=(
                    "[User follow-up sent while you are working] "
                    f"{question}\n\n"
                    "(You were busy with the current task and could not see "
                    "this earlier. Address it as soon as your current step "
                    "finishes — answer it directly, or fold it into your "
                    "remaining work. Do not ignore it.)"
                ),
            ),
            OpenAIBackendRole.USER,
        )
        logger.info(
            "Injected mid-run user question into live agent memory",
            extra={"question_length": len(question)},
        )
        return True
    except Exception:
        logger.warning(
            "Failed to inject mid-run user question into agent memory",
            exc_info=True,
        )
        return False


async def single_agent_solve(
    options: Chat,
    request: Request,
    task_lock: TaskLock,
    hands: IHands | None = None,
):
    pause_event = asyncio.Event()
    pause_event.set()
    agent = None
    running_turn: asyncio.Task[tuple[str, int]] | None = None
    current_task_id = options.task_id

    approval_manager = getattr(task_lock, "approval_manager", None)
    if approval_manager is None:
        approval_manager = ApprovalManager(task_lock)
        task_lock.approval_manager = approval_manager

    async def ensure_agent(task_id: str):
        nonlocal agent
        if agent is None:
            agent = await single_agent(
                options,
                task_id=task_id,
                hands=hands,
                pause_event=pause_event,
            )
        # Expose the live agent on the task lock so the "Clear agent context"
        # (soft-reset) endpoint can reach it. Safe: reset() only clears the
        # CAMEL message memory; the browser is a separate CDP process.
        try:
            task_lock.single_agent = agent
        except Exception:  # pragma: no cover - defensive
            pass
        observable_todo = getattr(agent, "_observable_todo_toolkit", None)
        if observable_todo is not None:
            observable_todo.task_id = task_id
            observable_todo.agent_id = agent.agent_id
            observable_todo.emit_todo_state()
        return agent

    async def run_turn(
        question: str,
        attaches: list[str],
        task_id: str,
        project_context: str | None = None,
    ) -> tuple[str, int]:
        was_reused = agent is not None
        turn_agent = await ensure_agent(task_id)
        turn_agent.process_task_id = task_id
        # STATELESS-PER-TURN MEMORY (the fix for the verbatim-repeat loop):
        # reset a REUSED agent's message history at the start of each turn,
        # keeping its system prompt, tools, and the EXTERNAL browser session
        # (reset() only clears CAMEL's message list — the CDP browser is a
        # separate process). Without this, memory accumulated every prior turn
        # (including the agent's own replies) and a low-temp model regurgitated
        # them instead of answering the new message. A COMPACT context is
        # rebuilt below; the agent pulls back specifics on demand via
        # recall_conversation.
        if was_reused:
            try:
                turn_agent.reset()
            except Exception:  # pragma: no cover - defensive
                logger.warning("per-turn agent reset failed", exc_info=True)
        # Every turn is now effectively fresh, so the compact background context
        # is rebuilt and injected as a system record each time.
        is_fresh_agent = True
        # Tool RAG: re-select the tools exposed to the model for THIS turn's
        # message (core + top-K relevant), so a topic shift on a follow-up gets
        # the right tools and we never carry the whole catalog on every step.
        selector = getattr(turn_agent, "_tool_rag_selector", None)
        if selector is not None:
            # Prefer the LLM router (it DECIDES which capabilities the task needs
            # from a compact catalog); it falls back to embeddings internally.
            # Set UNDISCLOSED_TOOL_ROUTER=0 to force the embeddings-only path.
            router_on = str(env("UNDISCLOSED_TOOL_ROUTER", "1")).strip().lower() not in {
                "0",
                "false",
                "no",
                "off",
            }
            if router_on:
                await reconcile_agent_tools_routed(
                    turn_agent,
                    selector,
                    getattr(turn_agent, "model_backend", None),
                    question,
                )
            else:
                reconcile_agent_tools(turn_agent, selector, question)

        # Collapse images from PRIOR turns to a text description before this
        # turn runs, so we never re-send old image bytes to the model. This
        # turn's own image (attached below) is added after and is seen once.
        await _collapse_memory_images(turn_agent)
        _fire_hook(emit_task_started(task_id=task_id))
        vision_capable = model_supports_vision(
            options.model_platform, options.model_type
        )
        prompt, bg_context = _build_single_agent_prompt(
            task_lock,
            question,
            attaches,
            project_context,
            vision_capable=vision_capable,
            memory_enabled=_memory_enabled(options),
            is_fresh_agent=is_fresh_agent,
            active_editor=options.active_editor,
        )
        # Inject recalled facts + earlier turns as a SYSTEM memory record so it
        # stays BACKGROUND: it never leaks into the UI (the user message is just
        # the question) and it stops competing with the current message, which is
        # what made the agent re-answer old, completed tasks on a fresh session.
        # Anti-repetition focus directive, placed in the RECENCY slot (the last
        # system message before the user's message). This fires on EVERY turn,
        # not just fresh ones: follow-ups reuse a persistent agent whose own
        # `memory` fills with its prior summaries, and a low-temp model then
        # mirrors that history instead of acting on a terse new message. The
        # directive right before the current message is what breaks that loop —
        # so it matters MOST on follow-ups (where bg_context is empty).
        _focus_directive = (
            "Now respond to the user's CURRENT message ONLY. If it is a short "
            "instruction or continuation (e.g. \"yes\", \"skip\", \"take "
            "control\", \"I clicked X\", \"continue\"), treat it as a directive "
            "and TAKE THE NEXT CONCRETE ACTION toward it — call the needed "
            "tools. Do NOT restate, re-summarize, or repeat any earlier "
            "response; everything before this is COMPLETED background only."
        )
        try:
            from camel.types import OpenAIBackendRole

            if bg_context.strip():
                system_note = (
                    "Background for this conversation (prior or related work, "
                    "for reference only). Do NOT answer, repeat, or redo it.\n\n"
                    + bg_context.strip()
                    + "\n\n=== END BACKGROUND ===\n"
                    + _focus_directive
                )
            else:
                system_note = _focus_directive
            turn_agent.update_memory(
                BaseMessage.make_system_message(
                    role_name="System", content=system_note
                ),
                OpenAIBackendRole.SYSTEM,
            )
        except Exception:
            logger.warning(
                "Failed to inject focus directive as system memory; "
                "prepending to the prompt instead.",
                exc_info=True,
            )
            prefix = _focus_directive
            if bg_context.strip():
                prefix = (
                    "[Background, reference only — do NOT answer this]\n"
                    + bg_context.strip()
                    + "\n\n"
                    + prefix
                )
            prompt = prefix + "\n\n" + prompt
        # Attach image files as vision content ONLY for models that can see them.
        # For text-only models (e.g. deepseek-chat) image_list is useless (or
        # rejected); the resolved paths in the prompt let the agent OCR them via
        # tools instead.
        attach_images = (
            _load_attach_images(attaches) if vision_capable else []
        )
        if attach_images:
            step_input: Any = BaseMessage.make_user_message(
                role_name="User",
                content=prompt,
                image_list=attach_images,
            )
        else:
            step_input = prompt
        response = await turn_agent.astep(step_input)
        content, total_tokens, reasoning = await _response_content(response)
        # Stash the model's reasoning so the 'end' emitter can surface it in a
        # collapsible "thinking" block (only for reasoning models + when enabled).
        task_lock.last_reasoning = reasoning
        record_agent_memory_snapshot(
            task_lock,
            turn_agent,
            scope="single_agent",
            task_id=task_id,
            task_content=question,
            task_result=content,
        )
        task_lock.add_conversation(
            "task_result",
            {
                "task_content": question,
                "task_result": content,
                "working_directory": get_working_directory(options, task_lock),
            },
        )
        return content, total_tokens

    pending_queue_get: asyncio.Task[Any] = asyncio.create_task(
        task_lock.get_queue()
    )

    # Follow-ups that arrived while a turn was running. A live turn can't be
    # steered mid-flight, so instead of only injecting the message into memory
    # (where it may never get its own answer), we defer it and run it as a
    # normal turn as soon as the current one finishes. Without this, a follow-up
    # sent mid-turn looks "skipped" until the user asks again.
    deferred_followups: list[ActionImproveData] = []

    def _start_turn_for_improve(item: ActionImproveData):
        """Set up and launch a run_turn for an improve/follow-up item."""
        nonlocal agent, running_turn, current_task_id
        if item.new_task_id:
            current_task_id = item.new_task_id
            set_current_task_id(options.project_id, current_task_id)
        if _apply_model_override(options, item.data) and agent is not None:
            logger.info(
                "Model changed on follow-up turn; rebuilding single agent",
                extra={"project_id": options.project_id},
            )
            agent = None
        pause_event.set()
        task_lock.status = Status.processing
        running_turn = asyncio.create_task(
            run_turn(
                item.data.question,
                item.data.attaches or [],
                current_task_id,
                item.data.project_context or options.project_context,
            )
        )
        task_lock.add_background_task(running_turn)

    try:
        while True:
            if await request.is_disconnected():
                logger.info(
                    "Single Agent client disconnected; pausing session",
                    extra={"project_id": options.project_id},
                )
                pause_event.clear()
                task_lock.status = Status.confirming
                if running_turn and not running_turn.done():
                    running_turn.cancel()
                break

            # As soon as the agent is idle, run the next follow-up that arrived
            # while it was busy (deferred above), as its own turn.
            if (
                running_turn is None
                and deferred_followups
                and pause_event.is_set()
            ):
                next_item = deferred_followups.pop(0)
                yield sse_json(
                    "confirmed",
                    {
                        "question": next_item.data.question,
                        "attaches": next_item.data.attaches or [],
                    },
                )
                _start_turn_for_improve(next_item)
                continue

            wait_for = {pending_queue_get}
            if running_turn is not None:
                wait_for.add(running_turn)

            done, _ = await asyncio.wait(
                wait_for,
                timeout=1.0,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                continue

            if pending_queue_get in done:
                item = pending_queue_get.result()
                pending_queue_get = asyncio.create_task(task_lock.get_queue())

                if item.action == Action.improve:
                    assert isinstance(item, ActionImproveData)

                    if running_turn is not None and not running_turn.done():
                        # A turn is already executing and can't be steered
                        # mid-flight. DEFER the follow-up so it runs as its own
                        # turn the moment the current one finishes — otherwise it
                        # would only live in memory and look skipped until the
                        # user re-asks. (No mid-run inject: that risked the
                        # current turn answering it AND the deferred turn
                        # answering it again.)
                        deferred_followups.append(item)
                        yield sse_json(
                            "notice",
                            {
                                "notice": (
                                    "Received your follow-up. The agent will "
                                    "address it as soon as the current task "
                                    "finishes."
                                ),
                                "process_task_id": current_task_id,
                            },
                        )
                        continue

                    # Not busy: run it now.
                    # Include attaches so the client can render (and, on replay,
                    # re-render) the user turn's image/file attachments.
                    yield sse_json(
                        "confirmed",
                        {
                            "question": item.data.question,
                            "attaches": item.data.attaches or [],
                        },
                    )
                    _start_turn_for_improve(item)
                    continue

                if item.action == Action.pause:
                    pause_event.clear()
                    task_lock.status = Status.confirming
                    _fire_hook(emit_session_paused(task_id=current_task_id))
                    continue

                if item.action == Action.resume:
                    pause_event.set()
                    task_lock.status = Status.processing
                    # While paused, the USER manually drove the browser — the
                    # agent has NO tool observations of what they did, so without
                    # this it fabricates the steps (e.g. inventing a PIN). Ground
                    # it in reality before it reports anything.
                    if agent is not None:
                        try:
                            agent.update_memory(
                                BaseMessage.make_user_message(
                                    role_name="User",
                                    content=(
                                        "[The user just took manual control of "
                                        "the browser and performed actions "
                                        "themselves — this may include entering "
                                        "credentials, PINs, OTPs, passwords, or "
                                        "completing/submitting forms.] You did "
                                        "NOT perform these actions and have no "
                                        "record of them. Before you report "
                                        "anything, use your browser tools (e.g. "
                                        "a page snapshot) to observe the ACTUAL "
                                        "current page. Never claim you entered a "
                                        "PIN, password, OTP, or credential, and "
                                        "never fabricate a confirmation or the "
                                        "steps taken — attribute anything done "
                                        "during manual control to the user."
                                    ),
                                ),
                                OpenAIBackendRole.USER,
                            )
                        except Exception:
                            logger.debug(
                                "take-control grounding inject failed",
                                exc_info=True,
                            )
                    _fire_hook(emit_session_resumed(task_id=current_task_id))
                    continue

                if item.action == Action.skip_task:
                    pause_event.clear()
                    stop_message = (
                        "<summary>Task stopped</summary>Task stopped by user"
                    )
                    # A tool blocked on governance approval (or anything else
                    # awaiting a plain asyncio.Future rather than cooperating
                    # with CancelledError promptly) would otherwise keep the
                    # cancelled turn alive in the background for up to the
                    # approval timeout. Resolve it immediately so nothing
                    # lingers past this Skip.
                    if approval_manager is not None:
                        approval_manager.cancel_all(
                            reason="task skipped by user"
                        )
                    cancelled_turn = running_turn
                    # Drop our reference first so the next asyncio.wait does
                    # not block on the cancelled task, and so the duplicate
                    # "end" path further down cannot re-surface it.
                    running_turn = None
                    if (
                        cancelled_turn is not None
                        and not cancelled_turn.done()
                    ):
                        cancelled_turn.cancel()

                        # Attach a done callback that swallows CancelledError /
                        # whatever exception the turn surfaces post-cancel, so
                        # the asyncio loop does not log "Task exception was
                        # never retrieved". We deliberately do NOT await the
                        # task here: model HTTP calls, browser actions, or
                        # MCP tool calls may not propagate CancelledError
                        # promptly, and awaiting would block the SSE response
                        # generator -- the user would press Skip and see
                        # nothing happen.
                        def _swallow(task: asyncio.Task) -> None:
                            try:
                                task.result()
                            except (asyncio.CancelledError, Exception):
                                pass

                        cancelled_turn.add_done_callback(_swallow)
                    task_lock.status = Status.done
                    _finalize_memory_for_turn(
                        task_lock,
                        state="cancelled",
                        final_result=stop_message,
                    )
                    yield sse_json("end", stop_message)
                    _fire_hook(emit_task_cancelled(task_id=current_task_id))
                    continue

                if item.action == Action.stop:
                    pause_event.clear()
                    if agent is not None and getattr(
                        agent, "stop_event", None
                    ):
                        agent.stop_event.set()
                    # Same rationale as Action.skip_task above: don't rely on
                    # CancelledError propagating promptly through whatever the
                    # turn is currently awaiting (a governance approval is a
                    # plain Future, not a cooperative tool call) -- resolve
                    # any pending approval directly so Stop can't be left
                    # waiting on it.
                    if approval_manager is not None:
                        approval_manager.cancel_all(reason="stopped by user")
                    if running_turn is not None and not running_turn.done():
                        running_turn.cancel()
                    _fire_hook(emit_task_cancelled(task_id=current_task_id))
                    await delete_task_lock(task_lock.id)
                    # Explicit terminal signal for the frontend instead of
                    # relying solely on the SSE connection closing after
                    # `break` -- mirrors Action.skip_task's "end" event so the
                    # UI reliably leaves the "running" state right away.
                    yield sse_json(
                        "end",
                        "<summary>Task stopped</summary>Task stopped by user",
                    )
                    break

                payload = _action_to_sse(item)
                if payload is not None:
                    if item.action == Action.budget_not_enough:
                        pause_event.clear()
                        task_lock.status = Status.confirming
                    yield payload
                continue

            if running_turn is not None and running_turn in done:
                try:
                    final_result, total_tokens = running_turn.result()
                except asyncio.CancelledError:
                    final_result = "<summary>Task paused</summary>Task paused"
                    total_tokens = 0
                except Exception as e:
                    logger.error(
                        "Single Agent turn failed",
                        extra={
                            "project_id": options.project_id,
                            "task_id": current_task_id,
                        },
                        exc_info=True,
                    )
                    pause_event.clear()
                    task_lock.status = Status.confirming
                    _finalize_memory_for_turn(
                        task_lock, state="failed", error=str(e)
                    )
                    yield sse_json("error", {"message": str(e)})
                    _fire_hook(
                        emit_task_failed(task_id=current_task_id, error=str(e))
                    )
                    running_turn = None
                    continue

                task_lock.status = Status.done
                running_turn = None
                _finalize_memory_for_turn(
                    task_lock,
                    state="done",
                    final_result=final_result,
                )
                end_payload: dict[str, Any] = {
                    "message": final_result,
                    "tokens": total_tokens,
                }
                # Surface the model's reasoning (thinking block) when the model
                # produced any and the user hasn't turned it off.
                reasoning = getattr(task_lock, "last_reasoning", "") or ""
                if (
                    reasoning
                    and _thinking_enabled(options)
                    and _is_meaningful_reasoning(reasoning, final_result)
                ):
                    end_payload["reasoning"] = reasoning
                task_lock.last_reasoning = ""
                yield sse_json("end", end_payload)
                _fire_hook(emit_task_completed(task_id=current_task_id))
                continue
    finally:
        if approval_manager is not None:
            try:
                approval_manager.cancel_all(reason="session ended")
            except Exception:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to cancel pending approvals",
                    extra={"project_id": options.project_id},
                    exc_info=True,
                )
        if pending_queue_get is not None and not pending_queue_get.done():
            pending_queue_get.cancel()
        if running_turn is not None and not running_turn.done():
            pause_event.clear()
            task_lock.status = Status.confirming
            running_turn.cancel()
        # If the loop exits without a clean done/failed end-of-turn (client
        # disconnect, stop, exception), record a cancelled run. The
        # `_memory_finalized_runs` set on task_lock makes this idempotent:
        # a prior done/failed write wins, this only catches the unfinished
        # case.
        _finalize_memory_for_turn(task_lock, state="cancelled")
        if agent is not None:
            release_cdp = getattr(agent, "_cdp_release_callback", None)
            if callable(release_cdp):
                try:
                    release_cdp(agent)
                except Exception:
                    logger.warning(
                        "Failed to release Single Agent browser resource",
                        extra={
                            "project_id": options.project_id,
                            "task_id": current_task_id,
                        },
                        exc_info=True,
                    )
