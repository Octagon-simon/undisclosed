// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========

import { generateUniqueId } from '@/lib';
import { proxyUpdateTriggerExecution } from '@/service/triggerApi';
import {
  closeSSEConnectionsForTasks,
  hasActiveSSEConnection,
} from '@/store/chatStore';
import { useProjectRuntimeStore } from '@/store/projectRuntimeStore';
import { useTriggerTaskStore } from '@/store/triggerTaskStore';
import { ExecutionStatus } from '@/types';
import { AgentStep, ChatTaskStatus } from '@/types/constants';
import { useCallback, useEffect, useRef } from 'react';
import { toast } from 'sonner';

/** Poll interval in ms */
const POLL_INTERVAL_MS = 2000;

interface ActiveBackgroundTask {
  projectId: string;
  chatTaskId: string;
  executionId: string;
  triggerTaskId?: string;
}

/**
 * Decide *why* a project's chat activity blocks starting a queued trigger task.
 * Returns a human-readable reason, or `null` if the project is free.
 *
 * Returning the reason instead of a bare boolean lets the skip breadcrumb name
 * the exact clause that matched, so a pending execution that never runs is
 * diagnosable straight from the panel devtools.
 */
function getBusyReason(
  chatStores: Record<string, { getState: () => any }>
): string | null {
  for (const cs of Object.values(chatStores || {})) {
    const state = cs.getState();
    for (const [taskId, raw] of Object.entries(state.tasks || {})) {
      const t = raw as {
        status?: string;
        messages?: Array<{ step?: string; isConfirm?: boolean }>;
        hasWaitComfirm?: boolean;
        isTakeControl?: boolean;
      };
      const messages = t.messages || [];
      if (t.status === ChatTaskStatus.RUNNING) {
        return `task ${taskId} RUNNING`;
      }
      if (t.status === ChatTaskStatus.PAUSE) {
        return `task ${taskId} PAUSED`;
      }
      if (
        messages.some(
          (m) => m.step === AgentStep.TO_SUB_TASKS && !m.isConfirm
        )
      ) {
        return `task ${taskId} splitting (to_sub_tasks unconfirmed)`;
      }
      // skeleton/computing phase — only while the task is still live. Without
      // the FINISHED guard a completed task (messages present, no to_sub_tasks
      // step) read as "running" forever, permanently starving queued triggers.
      if (
        t.status !== ChatTaskStatus.FINISHED &&
        !messages.find((m) => m.step === AgentStep.TO_SUB_TASKS) &&
        !t.hasWaitComfirm &&
        messages.length > 0
      ) {
        return `task ${taskId} skeleton/computing (status=${t.status}, ${messages.length} msgs)`;
      }
      if (t.isTakeControl) {
        return `task ${taskId} user take-control`;
      }
    }
  }
  return null;
}

/**
 * Hook that processes background tasks from project queuedMessages.
 * Supports trigger tasks (with executionId) and can be extended for other task types.
 *
 * - Polls all projects' queuedMessages for messages with executionId
 * - Uses appendInitChatStore + startTask for execution (supports same-project parallelism)
 */
export function useBackgroundTaskProcessor() {
  const projectStore = useProjectRuntimeStore();
  const triggerTaskStore = useTriggerTaskStore();

  const activeTasksRef = useRef<Map<string, ActiveBackgroundTask>>(new Map());
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isProcessingRef = useRef(false);
  // Last skip reason logged per project. Deduped so the 2s poll does not flood
  // the console with the same "skipping" line while a project stays blocked.
  const lastSkipRef = useRef<Map<string, string>>(new Map());

  // Breadcrumb a skipped/deferred project exactly once per distinct reason.
  const logSkip = useCallback((key: string, reason: string) => {
    if (lastSkipRef.current.get(key) === reason) return;
    lastSkipRef.current.set(key, reason);
    console.log(
      '[BackgroundTaskProcessor] Skipping project',
      key,
      '-',
      reason
    );
  }, []);

  const processOneTask = useCallback(async () => {
    if (isProcessingRef.current) return;
    isProcessingRef.current = true;
    try {
      const projects = projectStore.getAllProjects();
      let messageToProcess: {
        projectId: string;
        task_id: string;
        content: string;
        attaches: File[];
        executionId: string;
        triggerTaskId?: string;
        triggerId?: number;
        triggerName?: string;
        timestamp: number;
      } | null = null;

      for (const project of projects) {
        const projectData = projectStore.getProjectById(project.id);
        if (!projectData?.queuedMessages?.length) continue;

        // Per-project concurrency: skip if this project already has an active background task
        const hasActiveBackgroundTask = Array.from(
          activeTasksRef.current.values()
        ).some((t) => t.projectId === project.id);
        if (hasActiveBackgroundTask) {
          logSkip(project.id, 'already has an active background task');
          continue;
        }

        // Also check if any chat in this project has a running/paused task.
        // getBusyReason names the exact clause that matched, so the skip breadcrumb
        // is diagnosable instead of a bare boolean.
        const busyReason = getBusyReason(projectData.chatStores || {});
        if (busyReason) {
          logSkip(project.id, `has a running/paused chat task: ${busyReason}`);
          continue;
        }

        // If SSE is active, starting a new task would duplicate trigger processing.
        // Wait for the active task to finish; if task is done but SSE lingers, close it
        // so the trigger can start fresh on the next poll.
        const allTaskIds = Object.values(projectData.chatStores || {}).flatMap(
          (cs) => Object.keys(cs.getState().tasks)
        );
        if (hasActiveSSEConnection(allTaskIds)) {
          const activeChatStore = projectStore.getChatStore(project.id);
          const activeState = activeChatStore?.getState();
          const activeTaskId = activeState?.activeTaskId;
          const activeTask = activeTaskId
            ? activeState?.tasks[activeTaskId]
            : null;

          const isActiveTaskDone =
            activeTask?.status === ChatTaskStatus.FINISHED ||
            activeTask?.hasWaitComfirm;

          if (isActiveTaskDone) {
            console.log(
              '[BackgroundTaskProcessor] Closing stale SSE for project',
              project.id,
              '- active task done, trigger waiting in queue'
            );
            closeSSEConnectionsForTasks(allTaskIds);
          } else {
            logSkip(project.id, 'SSE active, task still in progress');
          }
          continue;
        }

        const msg = projectData.queuedMessages.find(
          (m) => m.executionId && !m.processing
        );
        if (msg && msg.executionId) {
          messageToProcess = {
            projectId: project.id,
            task_id: msg.task_id,
            content: msg.content,
            attaches: msg.attaches || [],
            executionId: msg.executionId,
            triggerTaskId: msg.triggerTaskId,
            triggerId: msg.triggerId,
            triggerName: msg.triggerName,
            timestamp: msg.timestamp,
          };
          break;
        }
      }

      if (!messageToProcess) {
        // Nothing startable this poll. Two distinct cases, both diagnostic:
        //  - trigger messages queued but all marked `processing`: a pass is
        //    mid-flight, so log which executions are in flight.
        //  - queue fully drained: clear dedupe state so the next real skip logs.
        const inFlight = projects.flatMap((p) => {
          const pd = projectStore.getProjectById(p.id);
          return (pd?.queuedMessages || [])
            .filter((m) => m.executionId && m.processing)
            .map((m) => `${m.executionId}@${p.id}`);
        });
        if (inFlight.length) {
          logSkip(
            '__in_flight__',
            `${inFlight.length} trigger execution(s) already in flight: ${inFlight.join(
              ', '
            )}`
          );
        } else {
          lastSkipRef.current.clear();
        }
        return;
      }

      const {
        projectId,
        task_id,
        content,
        attaches,
        executionId,
        triggerTaskId,
        triggerId,
        triggerName,
      } = messageToProcess;

      const newTaskId = generateUniqueId();

      // Track BEFORE markQueuedMessageAsProcessing — that call triggers
      // projectStore subscription → poll() → processOneTask() re-entrancy.
      // Having the guard set first ensures the per-project concurrency check
      // blocks any re-entrant attempt.
      activeTasksRef.current.set(executionId, {
        projectId,
        chatTaskId: newTaskId,
        executionId,
        triggerTaskId,
      });

      projectStore.markQueuedMessageAsProcessing(projectId, task_id);

      // This project is no longer skipped; reset its dedupe so a future skip
      // (after this task finishes) logs again.
      lastSkipRef.current.delete(projectId);

      console.log(
        '[BackgroundTaskProcessor] Marked message as processing:',
        task_id,
        'executionId:',
        executionId
      );

      try {
        // Get the latest project's chatStore
        const chatStore = projectStore.getChatStore(projectId);
        if (!chatStore) {
          throw new Error('Failed to get chat store for background task');
        }

        triggerTaskStore.registerExecutionMapping(
          newTaskId,
          executionId,
          triggerTaskId || task_id,
          projectId,
          triggerName,
          triggerId
        );

        // Notify backend that we're starting - prevents 60s timeout marking as "missed"
        // (WebSocket ack may not reach backend in some cases, e.g. multi-worker, connection issues)
        proxyUpdateTriggerExecution(
          executionId,
          { status: 'running' },
          { projectId, triggerId, triggerName }
        ).catch((err) =>
          console.warn(
            '[BackgroundTaskProcessor] Failed to update execution status to running:',
            err
          )
        );

        // Fire and forget - startTask streams until completion
        chatStore
          .getState()
          .startTask(
            newTaskId,
            undefined,
            undefined,
            undefined,
            content,
            attaches,
            executionId,
            projectId
          )
          .then(() => {
            console.log(
              '[BackgroundTaskProcessor] Background task completed:',
              executionId
            );
            // Remove from queue after successful completion
            projectStore.removeQueuedMessage(projectId, task_id);
            activeTasksRef.current.delete(executionId);
          })
          .catch((err: any) => {
            console.error(
              '[BackgroundTaskProcessor] Background task error:',
              err
            );
            // Remove from queue on error as well
            projectStore.removeQueuedMessage(projectId, task_id);
            // Report failure to backend
            proxyUpdateTriggerExecution(
              executionId,
              {
                status: ExecutionStatus.Failed,
                error_message: err?.message || 'Task failed',
              },
              { projectId, triggerId, triggerName }
            ).catch((e) =>
              console.warn(
                '[BackgroundTaskProcessor] Failed to report error status:',
                e
              )
            );
            toast.error('Background task failed', {
              description: err?.message || 'Unknown error',
            });
            activeTasksRef.current.delete(executionId);
          });

        console.log(
          '[BackgroundTaskProcessor] Started background task:',
          executionId,
          'for project',
          projectId
        );

        console.log(
          '[BackgroundTaskProcessor] Current active tasks:',
          Array.from(activeTasksRef.current.keys())
        );
      } catch (error: any) {
        console.error(
          '[BackgroundTaskProcessor] Failed to start background task:',
          error
        );
        // Remove from queue on error
        projectStore.removeQueuedMessage(projectId, task_id);
        // Report failure to backend
        proxyUpdateTriggerExecution(
          executionId,
          {
            status: ExecutionStatus.Failed,
            error_message: error?.message || 'Background task failed',
          },
          { projectId, triggerId, triggerName }
        ).catch((e) =>
          console.warn(
            '[BackgroundTaskProcessor] Failed to report error status:',
            e
          )
        );
        toast.error('Background task failed', {
          description: error?.message || 'Unknown error',
        });
        activeTasksRef.current.delete(executionId);
      }
    } finally {
      isProcessingRef.current = false;
    }
  }, [projectStore, triggerTaskStore, logSkip]);

  const checkCompletedTasks = useCallback(() => {
    const toRemove: string[] = [];

    activeTasksRef.current.forEach((task, executionId) => {
      const project = projectStore.getProjectById(task.projectId);
      if (!project?.chatStores) return;

      for (const chatStore of Object.values(project.chatStores)) {
        const state = chatStore.getState();
        const t = state.tasks[task.chatTaskId];
        if (t) {
          if (
            t.status !== ChatTaskStatus.RUNNING &&
            t.status !== ChatTaskStatus.PAUSE
          ) {
            toRemove.push(executionId);
          }
          break;
        }
      }
    });

    toRemove.forEach((executionId) => {
      activeTasksRef.current.delete(executionId);
    });
  }, [projectStore]);

  const poll = useCallback(() => {
    checkCompletedTasks();
    processOneTask();
  }, [checkCompletedTasks, processOneTask]);

  useEffect(() => {
    // Run poll immediately on mount - don't wait for first interval
    poll();

    const runPoll = () => {
      poll();
      pollTimerRef.current = setTimeout(runPoll, POLL_INTERVAL_MS);
    };

    pollTimerRef.current = setTimeout(runPoll, POLL_INTERVAL_MS);

    const unsubscribe = useProjectRuntimeStore.subscribe(() => {
      const state = useProjectRuntimeStore.getState();
      const hasTriggerTasks = Object.values(state.projects).some((p) =>
        p?.queuedMessages?.some((m) => m.executionId)
      );
      if (hasTriggerTasks) poll();
    });

    return () => {
      unsubscribe();
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [poll]);
}
