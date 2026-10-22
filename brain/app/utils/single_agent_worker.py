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

import asyncio
import datetime
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from camel.agents.chat_agent import (
    AsyncStreamingChatAgentResponse,
    ChatAgentResponse,
)
from camel.societies.workforce.prompts import PROCESS_TASK_PROMPT
from camel.societies.workforce.single_agent_worker import (
    SingleAgentWorker as BaseSingleAgentWorker,
)
from camel.societies.workforce.utils import TaskResult
from camel.tasks.task import Task, TaskState, is_task_result_insufficient
from camel.utils.context_utils import ContextUtility
from colorama import Fore

from app.agent.listen_chat_agent import ListenChatAgent, SegmentAccumulator
from app.agent.toolkit.observable_todo_toolkit import ObservableTodoToolkit
from app.service.task import get_task_lock
from app.service.turn_end_guard import (
    MAX_TURN_CONTINUATIONS,
    TurnEndState,
    classify_tool_records,
    evaluate_turn_end,
    should_auto_continue,
)
from app.utils.agent_memory import record_agent_memory_snapshot

logger = logging.getLogger("single_agent_worker")


def _todo_open(agent: Any) -> bool:
    """True when the worker's todo list still has an in-progress item."""
    toolkit = getattr(agent, "_observable_todo_toolkit", None)
    if not isinstance(toolkit, ObservableTodoToolkit):
        return False
    try:
        return any(
            str(item.get("status", "")).strip().lower()
            in ("in_progress", "in-progress")
            for item in toolkit.serialized_todos()
        )
    except Exception:
        return False


def _tokens_from_info(info: dict[str, Any]) -> int:
    usage = info.get("usage") or info.get("token_usage") or {}
    return int(usage.get("total_tokens", 0) or 0) if usage else 0


async def _consume_response(
    response: Any,
    stream_callback: Callable[[Any], Awaitable[None] | None] | None,
) -> tuple[str, Any, dict[str, Any], bool, list[Any]]:
    """Drive one agent response to completion.

    Returns ``(answer, parsed, info, answer_from_fallback, tool_records)``. The
    answer is the trailing segment after the last tool call (see
    ``SegmentAccumulator``); ``answer_from_fallback`` is True when that segment
    was empty and an earlier pre-tool-call one was kept instead.
    """
    if not isinstance(response, AsyncStreamingChatAgentResponse):
        msg = getattr(response, "msg", None)
        info = getattr(response, "info", None) or {}
        content = (getattr(msg, "content", "") or "") if msg else ""
        parsed = getattr(msg, "parsed", None) if msg else None
        return content, parsed, info, False, list(info.get("tool_calls") or [])

    segment = SegmentAccumulator()
    last_chunk = None
    parsed = None
    chunk_count = 0
    async for chunk in response:
        chunk_count += 1
        last_chunk = chunk
        if stream_callback:
            maybe = stream_callback(chunk)
            if asyncio.iscoroutine(maybe):
                await maybe
        segment.ingest(chunk)
        msg = getattr(chunk, "msg", None)
        if msg is not None and getattr(msg, "parsed", None) is not None:
            parsed = msg.parsed
    info = (getattr(last_chunk, "info", None) or {}) if last_chunk else {}
    response._last_chunk_info = info
    answer = segment.answer()
    logger.info(
        f"Streaming complete: {chunk_count} chunks, "
        f"content_length={len(answer)}"
    )
    return (
        answer,
        parsed,
        info,
        segment.from_fallback,
        list(info.get("tool_calls") or []),
    )


class SingleAgentWorker(BaseSingleAgentWorker):
    def __init__(
        self,
        description: str,
        worker: ListenChatAgent,
        use_agent_pool: bool = True,
        pool_initial_size: int = 0,  # Changed from 1 to 0 to avoid pre-creating clones that waste CDP resources
        pool_max_size: int = 10,
        auto_scale_pool: bool = True,
        use_structured_output_handler: bool = True,
        context_utility: ContextUtility | None = None,
        enable_workflow_memory: bool = False,
    ) -> None:
        logger.info(
            "Initializing SingleAgentWorker",
            extra={
                "description": description,
                "worker_agent_name": worker.agent_name,
                "use_agent_pool": use_agent_pool,
                "pool_max_size": pool_max_size,
                "enable_workflow_memory": enable_workflow_memory,
            },
        )
        super().__init__(
            description=description,
            worker=worker,
            use_agent_pool=use_agent_pool,
            pool_initial_size=pool_initial_size,
            pool_max_size=pool_max_size,
            auto_scale_pool=auto_scale_pool,
            use_structured_output_handler=use_structured_output_handler,
            context_utility=context_utility,
            enable_workflow_memory=enable_workflow_memory,
        )
        self.worker = worker  # change type hint

    async def _run_worker_step(
        self,
        worker_agent: ListenChatAgent,
        base_prompt: str,
        stream_callback: Callable[[Any], Awaitable[None] | None] | None,
    ) -> tuple[Any, str, TaskResult | None, int, bool, list[Any]]:
        """Run one worker step and read its response to completion.

        Returns ``(response, answer, task_result, tokens,
        answer_from_fallback, tool_records)``.
        """
        if self.use_structured_output_handler and self.structured_handler:
            # The schema lives in the prompt here, so a follow-up nudge has to
            # be wrapped the same way as the task prompt.
            prompt = self.structured_handler.generate_structured_prompt(
                base_prompt=base_prompt,
                schema=TaskResult,
                examples=[
                    {
                        "content": "I have successfully completed the task...",
                        "failed": False,
                    }
                ],
                additional_instructions="Ensure you provide a clear "
                "description of what was done and whether the task "
                "succeeded or failed.",
            )
            response = await worker_agent.astep(prompt)
            (
                answer,
                _,
                info,
                from_fallback,
                tool_records,
            ) = await _consume_response(response, stream_callback)
            task_result = self.structured_handler.parse_structured_response(
                response_text=answer,
                schema=TaskResult,
                fallback_values={
                    "content": "Task processing failed",
                    "failed": True,
                },
            )
            return (
                response,
                answer,
                task_result,
                _tokens_from_info(info),
                from_fallback,
                tool_records,
            )

        response = await worker_agent.astep(
            base_prompt, response_format=TaskResult
        )
        (
            answer,
            parsed,
            info,
            from_fallback,
            tool_records,
        ) = await _consume_response(response, stream_callback)
        if parsed is not None:
            task_result = parsed
        elif isinstance(response, AsyncStreamingChatAgentResponse):
            task_result = TaskResult(
                content="Failed to parse streaming response", failed=True
            )
        else:
            task_result = None
        return (
            response,
            answer,
            task_result,
            _tokens_from_info(info),
            from_fallback,
            tool_records,
        )

    async def _process_task(
        self,
        task: Task,
        dependencies: list[Task],
        stream_callback: Callable[
            ["ChatAgentResponse"], Awaitable[None] | None
        ]
        | None = None,
    ) -> TaskState:
        r"""Processes a task with its dependencies using an efficient agent
        management system.

        This method asynchronously processes a given task, considering its
        dependencies, by sending a generated prompt to a worker agent.
        Uses an agent pool for efficiency when enabled, or falls back to
        cloning when pool is disabled.

        Args:
            task (Task): The task to process, which includes necessary details
                like content and type.
            dependencies (List[Task]): Tasks that the given task depends on.

        Returns:
            TaskState: `TaskState.DONE` if processed successfully, otherwise
                `TaskState.FAILED`.
        """
        # Log task details before getting agent (for clone tracking)
        task_content_preview = (
            task.content[:100] + "..."
            if len(task.content) > 100
            else task.content
        )
        logger.debug(
            f"[TASK REQUEST] Requesting agent for task_id={task.id}, content_preview='{task_content_preview}'"
        )

        # Get agent efficiently (from pool or by cloning)
        worker_agent = await self._get_worker_agent()
        worker_agent.process_task_id = task.id  # type: ignore  rewrite line

        logger.info(
            "Starting task processing",
            extra={
                "task_id": task.id,
                "worker_agent_id": worker_agent.agent_id,
                "dependencies_count": len(dependencies),
            },
        )

        response_content = ""
        final_response = None
        try:
            dependency_tasks_info = self._get_dep_tasks_info(dependencies)
            prompt = PROCESS_TASK_PROMPT.format(
                content=task.content,
                parent_task_content=task.parent.content if task.parent else "",
                dependency_tasks_info=dependency_tasks_info,
                additional_info=task.additional_info,
            )

            total_tokens = 0
            response = None
            task_result = None
            # TURN-END VALIDATION: the same rule the single agent uses. A worker
            # whose step ends on an intent preamble ("Let me measure it
            # properly.") has not finished the task, so the step is nudged to
            # continue instead of being reported to the orchestrator as done.
            step_prompt = prompt
            for _attempt in range(MAX_TURN_CONTINUATIONS + 1):
                (
                    response,
                    response_content,
                    task_result,
                    step_tokens,
                    answer_from_fallback,
                    tool_records,
                ) = await self._run_worker_step(
                    worker_agent, step_prompt, stream_callback
                )
                total_tokens += step_tokens
                _state = TurnEndState(
                    question=task.content,
                    answer=response_content,
                    tool_rounds=len(tool_records),
                    todo_open=_todo_open(worker_agent),
                    action_request=False,
                    announce_continue=should_auto_continue(
                        response_content,
                        task.content,
                        tool_called=bool(tool_records),
                        answer_from_fallback=answer_from_fallback,
                    ),
                    outcomes=classify_tool_records(tool_records),
                )
                _decision = evaluate_turn_end(_state, _attempt)
                if not _decision.continue_turn:
                    break
                logger.info(
                    "turn-end: execution still owed (reason=%s, tool_calls=%s, "
                    "attempt %d/%d); auto-continuing worker on task %s",
                    _decision.reason,
                    _state.tool_rounds,
                    _attempt + 1,
                    MAX_TURN_CONTINUATIONS,
                    task.id,
                )
                step_prompt = _decision.nudge

            # collect conversation from working agent to
            # accumulator for workflow memory
            # Only transfer memory if workflow memory is enabled
            if self.enable_workflow_memory:
                accumulator = self._get_conversation_accumulator()

                # transfer all memory records from working agent to accumulator
                try:
                    # retrieve all context records from the working agent
                    work_records = worker_agent.memory.retrieve()

                    # write these records to the accumulator's memory
                    memory_records = [
                        record.memory_record for record in work_records
                    ]
                    accumulator.memory.write_records(memory_records)

                    logger.debug(
                        f"Transferred {len(memory_records)} memory records to accumulator"
                    )

                except Exception as e:
                    logger.warning(
                        f"Failed to transfer conversation to accumulator: {e}"
                    )

            try:
                task_lock = get_task_lock(worker_agent.api_task_id)
                record_agent_memory_snapshot(
                    task_lock,
                    worker_agent,
                    scope="workforce_worker",
                    task_id=task.id,
                    task_content=task.content,
                    task_result=response_content,
                )
            except Exception as e:
                logger.warning(f"Failed to record worker memory snapshot: {e}")

        except Exception as e:
            logger.error(
                f"Error processing task {task.id}: {type(e).__name__}: {e}"
            )
            # Store error information in task result
            task.result = f"{type(e).__name__}: {e!s}"
            return TaskState.FAILED
        finally:
            # Return agent to pool or let it be garbage collected
            await self._return_worker_agent(worker_agent)

        # Populate additional_info with worker attempt details
        if task.additional_info is None:
            task.additional_info = {}

        # Create worker attempt details with descriptive keys
        # Use final_response if available (streaming), otherwise use response
        response_for_info = (
            final_response if final_response is not None else response
        )
        worker_attempt_details = {
            "agent_id": getattr(
                worker_agent,
                "agent_id",
                getattr(worker_agent, "role_name", ""),
            ),
            "original_worker_id": getattr(
                self.worker, "agent_id", getattr(self.worker, "role_name", "")
            ),
            "timestamp": str(datetime.datetime.now()),
            "description": f"Attempt by "
            f"{getattr(worker_agent, 'agent_id', getattr(worker_agent, 'role_name', ''))} "
            f"(from pool/clone of "
            f"{getattr(self.worker, 'agent_id', getattr(self.worker, 'role_name', ''))}) "
            f"to process task: {task.content}",
            "response_content": response_content[:50],
            "tool_calls": str(
                response_for_info.info.get("tool_calls", [])
                if response_for_info and hasattr(response_for_info, "info")
                else []
            )[:50],
            "total_tokens": total_tokens,
        }

        # Store the worker attempt in additional_info
        if "worker_attempts" not in task.additional_info:
            task.additional_info["worker_attempts"] = []
        task.additional_info["worker_attempts"].append(worker_attempt_details)

        # Store the actual token usage for this specific task
        task.additional_info["token_usage"] = {"total_tokens": total_tokens}

        print(f"======\n{Fore.GREEN}Response from {self}:{Fore.RESET}")

        logger.info(f"Response from {self}:")

        if not self.use_structured_output_handler:
            # Handle native structured output parsing
            if task_result is None:
                logger.error(
                    "Error in worker step execution: Invalid task result"
                )
                print(
                    f"{Fore.RED}Error in worker step execution: Invalid task result{Fore.RESET}"
                )
                task_result = TaskResult(
                    content="Failed to generate valid task result.",
                    failed=True,
                )

        color = Fore.RED if task_result.failed else Fore.GREEN  # type: ignore[union-attr]
        print(
            f"\n{color}{task_result.content}{Fore.RESET}\n======",  # type: ignore[union-attr]
        )

        if task_result.failed:  # type: ignore[union-attr]
            logger.error(f"{task_result.content}")  # type: ignore[union-attr]
        else:
            logger.info(f"{task_result.content}")  # type: ignore[union-attr]

        task.result = task_result.content  # type: ignore[union-attr]

        if task_result.failed:  # type: ignore[union-attr]
            return TaskState.FAILED

        if is_task_result_insufficient(task):
            logger.warning(
                f"Task {task.id}: Content validation failed - task marked as failed"
            )
            return TaskState.FAILED
        return TaskState.DONE
