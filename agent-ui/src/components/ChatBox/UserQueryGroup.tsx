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

import { inferSessionModeFromTask } from '@/lib/sessionMode';
import { VanillaChatStore } from '@/store/chatStore';
import { usePageTabStore } from '@/store/pageTabStore';
import { AgentStep, ChatTaskStatus, SessionMode } from '@/types/constants';
import { motion } from 'framer-motion';
import { ChevronDown, FileText } from 'lucide-react';
import React, {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from 'react';
import { AgentMessageCard } from './MessageItem/AgentMessageCard';
import { ApprovalOutcomeCard } from './MessageItem/ApprovalOutcomeCard';
import { NoticeCard } from './MessageItem/NoticeCard';
import { PreparingToExecuteTasks } from './MessageItem/PreparingToExecuteTasks';
import { TaskWorkLogAccordion } from './MessageItem/TaskWorkLogAccordion';
import { UserMessageCard } from './MessageItem/UserMessageCard';
import { ThinkingBlock } from './MessageItem/ThinkingBlock';
import { FilesChanged } from './MessageItem/FilesChanged';
import { useHost } from '@/host';
import { extractChangedFiles } from '@/lib/activityClassifier';
import { PlanTaskBox } from './TaskBox/PlanTaskBox';
import { isPlanSplittingPhase } from './TaskBox/PlanTaskBox/utils';
import { TaskCard } from './TaskBox/TaskCard';

/**
 * Marker for the durable project-context block that the backend injects into
 * the system prompt on every request. It is echoed back into the chat, so it
 * surfaces as a generic agent message; we detect it here and render it
 * inside a collapsible group (just like the activity trace) instead of an
 * always-expanded wall of text.
 */
interface PromptBlock {
  title: string;
  content: string;
}

function extractPromptBlocks(content: string): { promptBlocks: PromptBlock[]; cleanedContent: string } {
  if (typeof content !== 'string') {
    return { promptBlocks: [], cleanedContent: content };
  }

  const promptBlocks: PromptBlock[] = [];
  let cleaned = content;

  // 1. Extract <remembered_facts> block
  const rememberedStart = cleaned.indexOf('<remembered_facts>');
  const rememberedEnd = cleaned.indexOf('</remembered_facts>');
  if (rememberedStart !== -1 && rememberedEnd !== -1 && rememberedEnd > rememberedStart) {
    const rawBlock = cleaned.slice(rememberedStart, rememberedEnd + '</remembered_facts>'.length);
    const innerContent = cleaned.slice(rememberedStart + '<remembered_facts>'.length, rememberedEnd).trim();
    promptBlocks.push({
      title: 'Remembered Facts',
      content: innerContent,
    });
    cleaned = cleaned.replace(rawBlock, '');
  }

  // 2. Extract === Persisted Project Context === block
  const contextStart = cleaned.indexOf('=== Persisted Project Context ===');
  const contextEnd = cleaned.indexOf('=== End Persisted Project Context ===');
  if (contextStart !== -1 && contextEnd !== -1 && contextEnd > contextStart) {
    const rawBlock = cleaned.slice(contextStart, contextEnd + '=== End Persisted Project Context ==='.length);
    const innerContent = cleaned.slice(contextStart + '=== Persisted Project Context ==='.length, contextEnd).trim();
    promptBlocks.push({
      title: 'Persisted Project Context',
      content: innerContent,
    });
    cleaned = cleaned.replace(rawBlock, '');
  }

  // 3. Extract === CURRENT MESSAGE === block
  const currentMsgStart = cleaned.indexOf('=== CURRENT MESSAGE — respond to THIS ===');
  const currentMsgEnd = cleaned.indexOf('=== END CURRENT MESSAGE ===');
  if (currentMsgStart !== -1 && currentMsgEnd !== -1 && currentMsgEnd > currentMsgStart) {
    const rawBlock = cleaned.slice(currentMsgStart, currentMsgEnd + '=== END CURRENT MESSAGE ==='.length);
    cleaned = cleaned.replace(rawBlock, '');
  }

  // 4. Strip any residual respond instructions paragraphs if the model leaked them
  const instructionsIdx = cleaned.indexOf('Respond ONLY to the current message above.');
  if (instructionsIdx !== -1) {
    const instructionEnd = cleaned.indexOf('earlier claims.', instructionsIdx);
    if (instructionEnd !== -1) {
      cleaned = cleaned.slice(0, instructionsIdx) + cleaned.slice(instructionEnd + 'earlier claims.'.length);
    } else {
      cleaned = cleaned.replace('Respond ONLY to the current message above.', '');
    }
  }

  return {
    promptBlocks,
    cleanedContent: cleaned.trim(),
  };
}

const PERSISTED_CONTEXT_HEADER = 'Persisted Project Context';

/** Collapsible card that shows the durable project context block or remembered facts, 
 * collapsed by default so it doesn't dominate the turn like the rest of the activity trace. */
const PersistedContextCard: React.FC<{ id: string; content: string; title?: string }> = ({
  id,
  content,
  title = 'Persisted Project Context',
}) => {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="overflow-hidden px-2">
      {/* Header (always visible) */}
      <button
        type="button"
        aria-expanded={isOpen}
        className="focus-visible:ring-ds-border-brand-default-focus/40 flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left transition-colors hover:bg-ds-bg-neutral-default-hover focus-visible:outline-none focus-visible:ring-2 active:bg-ds-bg-neutral-default-active"
        onClick={() => setIsOpen((v) => !v)}
      >
        <ChevronDown
          size={14}
          aria-hidden
          className={`shrink-0 text-ds-icon-neutral-default-default transition-transform duration-200 ${
            isOpen ? 'rotate-0' : '-rotate-90'
          }`}
        />
        <span className="min-w-0 flex-1 truncate text-sm font-semibold text-ds-text-neutral-default-default">
          {title}
        </span>
        <span className="shrink-0 rounded-full bg-ds-bg-neutral-muted-default px-1.5 py-0.5 text-label-xs text-ds-text-neutral-subtle-default">
          {isOpen ? 'hide' : 'expand'}
        </span>
      </button>

      {/* Collapsible body */}
      <div
        className={`duration-[160ms] ease-[cubic-bezier(0.23,1,0.32,1)] overflow-hidden transition-all ${
          isOpen ? 'max-h-[2000px] opacity-100' : 'max-h-0 opacity-0'
        }`}
      >
        <div className="border-t border-ds-border-neutral-default-default px-1 py-1">
          <AgentMessageCard
            id={id}
            content={content}
            typewriter={false}
            onTyping={() => {}}
          />
        </div>
      </div>
    </div>
  );
};

/** Collapsible card that shows a single agent's result (workforce / non–single-agent turns). */
const AgentResultCard: React.FC<{
  id: string;
  agentName?: string;
  content: string;
  attaches?: any[];
  defaultOpen?: boolean;
}> = ({ id, agentName, content, attaches, defaultOpen = false }) => {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const label = agentName || 'Agent';

  return (
    <div className="overflow-hidden px-2">
      {/* Header (always visible) */}
      <button
        type="button"
        className="focus-visible:ring-ds-border-brand-default-focus/40 flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm font-semibold text-ds-text-neutral-default-default transition-colors hover:bg-ds-bg-neutral-default-hover focus-visible:outline-none focus-visible:ring-2 active:bg-ds-bg-neutral-default-active"
        onClick={() => setIsOpen((v) => !v)}
      >
        <span className="min-w-0 flex-1 truncate">{label}</span>
        <ChevronDown
          size={14}
          aria-hidden
          className={`shrink-0 text-ds-icon-neutral-default-default transition-transform duration-200 ${isOpen ? 'rotate-180' : 'rotate-0'}`}
        />
      </button>

      {/* Collapsible body */}
      <div
        className={`duration-[160ms] ease-[cubic-bezier(0.23,1,0.32,1)] overflow-hidden transition-opacity ${isOpen ? 'max-h-[2000px] opacity-100' : 'max-h-0 opacity-0'}`}
      >
        <div className="border-t border-ds-border-neutral-default-default px-1 py-1">
          <AgentMessageCard
            id={id}
            content={content}
            typewriter={false}
            onTyping={() => {}}
            attaches={attaches}
          />
        </div>
      </div>
    </div>
  );
};

/** Typewriter only for the agent message currently being produced (latest agent row while task is running). */
function shouldUseLiveAgentTypewriter(
  task: {
    type?: string;
    delayTime?: number;
    status: string;
    messages: any[];
  } | null,
  messageId: string
): boolean {
  const replayAllows =
    task?.type !== 'replay' ||
    (task?.type === 'replay' && task?.delayTime !== 0);
  if (!replayAllows) return false;
  if (!task || task.status !== ChatTaskStatus.RUNNING) return false;
  const msgs = task.messages;
  if (!msgs.length) return false;
  const last = msgs[msgs.length - 1];
  return last.role === 'agent' && last.id === messageId;
}

interface QueryGroup {
  queryId: string;
  userMessage: any;
  taskMessage?: any;
  otherMessages: any[];
}

interface UserQueryGroupProps {
  chatId: string;
  chatStore: VanillaChatStore;
  queryGroup: QueryGroup;
  isActive: boolean;
  onQueryActive: (queryId: string | null) => void;
  index: number;
  /**
   * The task this query group belongs to. When provided, all task-derived
   * UI (TaskCard summary, PlanTaskBox state, work log) reflects THIS task
   * instead of `chatStore.activeTaskId` (which is the latest task and would
   * make every historic group repaint with the newest summary).
   */
  taskId?: string;
}

export const UserQueryGroup: React.FC<UserQueryGroupProps> = ({
  chatId,
  chatStore,
  queryGroup,
  isActive: _isActive,
  onQueryActive,
  index,
  taskId: scopedTaskId,
}) => {
  const groupRef = useRef<HTMLDivElement>(null);
  const chatState = chatStore.getState();

  const activeTaskId = scopedTaskId ?? chatState.activeTaskId;
  const openFilePreviewInPanel = usePageTabStore(
    (state) => state.openFilePreview
  );
  const host = useHost();
  const openFilePreview = useCallback(
    (file: FileInfo) => {
      // In the embed, open the real file in the Theia editor. The desktop
      // page-tab preview store isn't mounted here, so it silently did nothing.
      if (host?.openFile && file?.path) {
        void host.openFile(file.path);
        return;
      }
      openFilePreviewInPanel(file);
    },
    [host, openFilePreviewInPanel]
  );

  // Subscribe to streaming decompose text separately for efficient updates
  const streamingDecomposeText = useSyncExternalStore(
    (callback) => chatStore.subscribe(callback),
    () => {
      const state = chatStore.getState();
      const taskId = activeTaskId;
      if (!taskId || !state.tasks[taskId]) return '';
      return state.tasks[taskId].streamingDecomposeText || '';
    }
  );

  // Show task if this query group has a task message OR if it's the most recent user query during splitting
  // During splitting phase (no to_sub_tasks yet), show task for the most recent query only
  // Exclude human-reply scenarios (when user is replying to an activeAsk)
  const isHumanReply =
    queryGroup.userMessage &&
    activeTaskId &&
    chatState.tasks[activeTaskId] &&
    (chatState.tasks[activeTaskId].activeAsk ||
      // Check if this user message follows an 'ask' message in the message sequence
      (() => {
        const messages = chatState.tasks[activeTaskId].messages;
        const userMessageIndex = messages.findIndex(
          (m: any) => m.id === queryGroup.userMessage.id
        );
        if (userMessageIndex > 0) {
          // Check the previous message - if it's an agent message with step 'ask', this is a human-reply
          const prevMessage = messages[userMessageIndex - 1];
          return (
            prevMessage?.role === 'agent' && prevMessage?.step === AgentStep.ASK
          );
        }
        return false;
      })());

  const activeTask = activeTaskId ? chatState.tasks[activeTaskId] : undefined;
  const lastUserMessageId = activeTask?.messages
    .filter((m: any) => m.role === 'user')
    .pop()?.id;
  const isCurrentUserQuery = Boolean(
    !queryGroup.taskMessage &&
    !isHumanReply &&
    activeTask &&
    queryGroup.userMessage &&
    queryGroup.userMessage.id === lastUserMessageId
  );
  const isLastUserQuery =
    isCurrentUserQuery &&
    // Only show during active phases (not finished)
    activeTask?.status !== ChatTaskStatus.FINISHED;

  const isSingleAgentTask =
    inferSessionModeFromTask(activeTask, SessionMode.WORKFORCE) ===
    SessionMode.SINGLE_AGENT;
  const hasUnconfirmedPlan = Boolean(
    activeTask?.messages.some(
      (m: any) => m.step === AgentStep.TO_SUB_TASKS && !m.isConfirm
    )
  );
  const isInitialTaskPreparation = Boolean(
    isLastUserQuery &&
    activeTask?.isPending &&
    streamingDecomposeText.length === 0 &&
    !activeTask.messages.some((m: any) => m.step === AgentStep.TO_SUB_TASKS)
  );
  // Single agent has no task-splitting/confirm step — it runs directly — so it
  // never has a planning phase. Skipping this avoids the splitting card
  // showing during the PENDING window after the backend `confirmed` event.
  const isPlanningPhase = Boolean(
    activeTask &&
    !isSingleAgentTask &&
    !activeTask.hasWaitComfirm &&
    (isPlanSplittingPhase(activeTask) ||
      streamingDecomposeText.length > 0 ||
      hasUnconfirmedPlan)
  );

  // Show the fallback task box for the newest query only while the agent is
  // actually planning. Direct running tasks without `to_sub_tasks` should stay
  // in the normal running/input path.
  const shouldShowFallbackTask =
    isLastUserQuery && activeTaskId && isPlanningPhase;
  // Single agent has no split/confirm step: once the task is the current
  // query and past planning, show its task-card area immediately — even while
  // PENDING — so the "Preparing to execute" item can render before the work
  // log. `TaskWorkLogAccordion` self-hides until the task reaches RUNNING.
  const shouldShowSingleAgentWorkLog =
    isCurrentUserQuery &&
    activeTaskId &&
    activeTask &&
    isSingleAgentTask &&
    !isPlanningPhase &&
    !isHumanReply;

  const task =
    (queryGroup.taskMessage ||
      shouldShowFallbackTask ||
      shouldShowSingleAgentWorkLog) &&
    activeTaskId
      ? chatState.tasks[activeTaskId]
      : null;

  // Set up intersection observer for this query group
  useEffect(() => {
    if (!groupRef.current) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            onQueryActive(queryGroup.queryId);
          }
        });
      },
      {
        rootMargin: '-20% 0px -60% 0px',
        threshold: 0.1,
      }
    );

    observer.observe(groupRef.current);

    return () => {
      observer.disconnect();
    };
  }, [queryGroup.queryId, onQueryActive]);

  // Check if we're in skeleton phase — never for single agent (no splitting).
  // Gate on `isLastUserQuery`: historic turns that quit before emitting
  // `to_sub_tasks` (e.g. context_too_long, browser-aborted, parent killed)
  // would otherwise satisfy `isPlanSplittingPhase` forever and each render
  // its own "Subtasks Planning" spinner. Only the current/latest turn should
  // show the live splitting UI; abandoned turns fall through to taskCardVisible
  // and the conditional below renders nothing instead of a stale spinner.
  const isSkeletonPhase =
    task &&
    !isSingleAgentTask &&
    isPlanSplittingPhase(task) &&
    isLastUserQuery &&
    !isInitialTaskPreparation;

  /** Task card visible (user message is sticky alone in this mode). */
  const taskCardVisible = Boolean(task) && !isSkeletonPhase && !isHumanReply;
  const showTaskPlanCard =
    taskCardVisible &&
    !shouldShowSingleAgentWorkLog &&
    !isInitialTaskPreparation;

  const hasConfirmedSubTasks = Boolean(
    task?.messages.some(
      (m: any) => m.step === AgentStep.TO_SUB_TASKS && m.isConfirm
    )
  );
  const showPreparingExecute =
    Boolean(activeTaskId && task) &&
    task!.status === ChatTaskStatus.PENDING &&
    (isInitialTaskPreparation ||
      // Workforce: after the user confirms the plan, before the work log.
      (showTaskPlanCard && hasConfirmedSubTasks) ||
      // Single agent: from submit until the first `todo_state` arrives.
      shouldShowSingleAgentWorkLog);
  const shouldShowPlanTaskBox = Boolean(
    !hasConfirmedSubTasks && (isLastUserQuery || queryGroup.taskMessage)
  );

  return (
    <motion.div
      ref={groupRef}
      data-query-id={queryGroup.queryId}
      data-task-card={taskCardVisible ? 'true' : undefined}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.3,
        delay: index * 0.1, // Stagger animation for multiple groups
      }}
      className="relative"
    >
      {/* User query: always rendered as a regular component in the chat flow. */}
      {queryGroup.userMessage && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="px-sm py-sm"
        >
          <UserMessageCard
            id={queryGroup.userMessage.id}
            content={queryGroup.userMessage.content}
            attaches={queryGroup.userMessage.attaches}
          />
        </motion.div>
      )}

      {showTaskPlanCard && activeTaskId && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{
            opacity: 1,
            y: 0,
          }}
          transition={{
            duration: 0.3,
            delay: 0.1,
          }}
        >
          <div
            style={{
              transition: 'all 0.3s ease-in-out',
              transformOrigin: 'top',
            }}
          >
            {
              hasConfirmedSubTasks ? (
                <TaskCard
                  key={`task-${activeTaskId}-${queryGroup.queryId}`}
                  chatId={chatId}
                  taskId={activeTaskId}
                  taskInfo={task?.taskInfo || []}
                  taskType={queryGroup.taskMessage?.taskType || 1}
                  taskAssigning={task?.taskAssigning || []}
                  taskRunning={task?.taskRunning || []}
                  progressValue={task?.progressValue || 0}
                  summaryTask={task?.summaryTask || ''}
                  onAddTask={() => {
                    chatState.addTaskInfo();
                  }}
                  onUpdateTask={(taskIndex, content) => {
                    chatState.updateTaskInfo(taskIndex, content);
                  }}
                  onSaveTask={() => {
                    chatState.saveTaskInfo();
                  }}
                  onDeleteTask={(taskIndex) => {
                    chatState.deleteTaskInfo(taskIndex);
                  }}
                  clickable={true}
                />
              ) : shouldShowPlanTaskBox ? (
                // Live planning UI: latest splitting turn or the group that
                // owns an unconfirmed to_sub_tasks message.
                <PlanTaskBox
                  chatStore={chatStore}
                  taskId={activeTaskId}
                  userPrompt={queryGroup.userMessage?.content}
                />
              ) : null /* historic turn that never confirmed a plan: skip the stale spinner */
            }
          </div>
        </motion.div>
      )}

      {/* Turn-start acknowledgement — the agent's opening line, rendered as a
          normal agent message ABOVE the work log so it reads as "On it…" then
          the work, then the answer. (Env-gated on the backend; empty when off.) */}
      {task?.acknowledgement ? (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.2 }}
        >
          <AgentMessageCard
            id={`ack-${activeTaskId}`}
            content={task.acknowledgement}
            typewriter={false}
            onTyping={() => {}}
            hideFeedbackAndCopyBtn
          />
        </motion.div>
      ) : null}

      {taskCardVisible && activeTaskId && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25, delay: 0.05 }}
          className="px-6"
        >
          {showPreparingExecute ? <PreparingToExecuteTasks /> : null}
          <TaskWorkLogAccordion chatStore={chatStore} taskId={activeTaskId} />
        </motion.div>
      )}

      {/* Other Messages */}
      {queryGroup.otherMessages.map((message) => {
        if (message.content.length > 0) {
          if (message.step === AgentStep.APPROVAL_OUTCOME) {
            return (
              <motion.div
                key={`approval-outcome-${message.id}`}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.1 }}
                className="px-6"
              >
                <ApprovalOutcomeCard
                  content={message.content}
                  decision={message.decision}
                />
              </motion.div>
            );
          }
          if (message.step === AgentStep.END) {
            return (
              <motion.div
                key={`end-${message.id}`}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 }}
                className="flex flex-col gap-4"
              >
                {message.reasoning ? (
                  <ThinkingBlock reasoning={message.reasoning} />
                ) : null}
                <AgentMessageCard
                  typewriter={shouldUseLiveAgentTypewriter(task, message.id)}
                  id={message.id}
                  content={message.content}
                  onTyping={() => {}}
                  // A user-stopped turn (summary "Task stopped") isn't a real
                  // answer — there's nothing to thumbs-up/down or copy.
                  hideFeedbackAndCopyBtn={message.content === 'Task stopped'}
                  deferredFooter={
                    message.fileList?.length ? (
                      <div className="my-2 flex flex-wrap gap-2">
                        {message.fileList.map(
                          (file: any, fileIndex: number) => (
                            <motion.div
                              key={`file-${message.id}-${file.name}-${fileIndex}`}
                              initial={{ opacity: 0, scale: 0.9 }}
                              animate={{ opacity: 1, scale: 1 }}
                              transition={{ delay: 0.05 }}
                              onClick={() => {
                                openFilePreview(file);
                              }}
                              className="flex w-[140px] cursor-pointer items-center gap-2 rounded-lg bg-ds-bg-neutral-default-default px-3 py-2 transition-colors hover:bg-ds-bg-neutral-default-hover"
                            >
                              <FileText
                                size={16}
                                className="flex-shrink-0 text-ds-icon-neutral-default-default"
                              />
                              <div className="flex flex-col">
                                <div className="max-w-[100px] overflow-hidden text-ellipsis whitespace-nowrap text-body-sm font-bold text-ds-text-neutral-default-default">
                                  {file.name.split('.')[0]}
                                </div>
                                <div className="text-label-xs font-medium text-ds-text-neutral-muted-default">
                                  {file.type}
                                </div>
                              </div>
                            </motion.div>
                          )
                        )}
                      </div>
                    ) : undefined
                  }
                />
                {(() => {
                  const changed = extractChangedFiles(task?.taskAssigning);
                  return changed.length ? (
                    <FilesChanged
                      files={changed}
                      onOpen={(p) => void host?.openFile?.(p)}
                    />
                  ) : null;
                })()}
              </motion.div>
            );
          } else if (message.content === 'skip') {
            return (
              <motion.div
                key={`skip-${message.id}`}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 }}
                className="flex flex-col gap-4"
              >
                <AgentMessageCard
                  key={message.id}
                  id={message.id}
                  content="No reply received, task continues..."
                  onTyping={() => {}}
                />
              </motion.div>
            );
          } else if (message.step === AgentStep.AGENT_END) {
            const { promptBlocks, cleanedContent } = extractPromptBlocks(message.content);
            return (
              <div className="flex flex-col gap-4">
                {promptBlocks.map((block, idx) => (
                  <motion.div
                    key={`extracted-block-${message.id}-${idx}`}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.2 }}
                    className="px-6"
                  >
                    <PersistedContextCard
                      id={`${message.id}-block-${idx}`}
                      content={block.content}
                      title={block.title}
                    />
                  </motion.div>
                ))}
                {cleanedContent && (
                  <motion.div
                    key={`agent-end-${message.id}`}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.2 }}
                    className="px-6"
                  >
                    <AgentResultCard
                      id={message.id}
                      agentName={message.agent_name}
                      content={cleanedContent}
                      attaches={message.attaches}
                      defaultOpen
                    />
                  </motion.div>
                )}
              </div>
            );
          } else {
            const { promptBlocks, cleanedContent } = extractPromptBlocks(message.content);

            if (promptBlocks.length > 0) {
              return (
                <div className="flex flex-col gap-4">
                  {promptBlocks.map((block, idx) => (
                    <motion.div
                      key={`extracted-block-${message.id}-${idx}`}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: 0.2 }}
                      className="px-6"
                    >
                      <PersistedContextCard
                        id={`${message.id}-block-${idx}`}
                        content={block.content}
                        title={block.title}
                      />
                    </motion.div>
                  ))}
                  {cleanedContent && (
                    <motion.div
                      key={`message-${message.id}`}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: 0.2 }}
                      className="flex flex-col gap-4"
                    >
                      <AgentMessageCard
                        key={message.id}
                        typewriter={shouldUseLiveAgentTypewriter(task, message.id)}
                        id={message.id}
                        content={cleanedContent}
                        onTyping={() => {}}
                        attaches={message.attaches}
                      />
                    </motion.div>
                  )}
                </div>
              );
            }

            return (
              <motion.div
                key={`message-${message.id}`}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 }}
                className="flex flex-col gap-4"
              >
                <AgentMessageCard
                  key={message.id}
                  typewriter={shouldUseLiveAgentTypewriter(task, message.id)}
                  id={message.id}
                  content={cleanedContent}
                  onTyping={() => {}}
                  attaches={message.attaches}
                  // The legacy-replay failure notice is a system message, not an
                  // agent answer — no feedback/copy affordances.
                  hideFeedbackAndCopyBtn={cleanedContent.includes(
                    'Unable to replay this legacy task'
                  )}
                />
              </motion.div>
            );
          }
        } else if (message.step === AgentStep.END && message.content === '') {
          return (
            <motion.div
              key={`end-empty-${message.id}`}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.2 }}
              className="flex flex-col gap-4"
            >
              {message.fileList && (
                <div className="flex flex-wrap gap-2">
                  {message.fileList.map((file: any, fileIndex: number) => (
                    <motion.div
                      key={`file-${message.id}-${file.name}-${fileIndex}`}
                      initial={{ opacity: 0, scale: 0.9 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ delay: 0.3 }}
                      onClick={() => {
                        openFilePreview(file);
                      }}
                      className="flex w-[120px] cursor-pointer items-center gap-2 rounded-2xl bg-ds-bg-neutral-default-default px-2 py-1 transition-colors hover:bg-ds-bg-neutral-default-hover"
                    >
                      <FileText
                        size={16}
                        className="flex-shrink-0 text-ds-icon-neutral-default-default"
                      />
                      <div className="flex flex-col">
                        <div className="text-body max-w-48 overflow-hidden text-ellipsis whitespace-nowrap text-sm font-bold text-ds-text-neutral-default-default">
                          {file.name.split('.')[0]}
                        </div>
                        <div className="text-xs font-medium leading-29 text-ds-text-neutral-default-default">
                          {file.type}
                        </div>
                      </div>
                    </motion.div>
                  ))}
                </div>
              )}
            </motion.div>
          );
        }

        // Notice Card
        if (
          message.step === AgentStep.NOTICE_CARD &&
          !task?.isTakeControl &&
          task?.cotList &&
          task.cotList.length > 0
        ) {
          return <NoticeCard key={`notice-${message.id}`} />;
        }

        return null;
      })}

      {/* PlanTaskBox now owns streaming + skeleton splitting UI for the active task. */}
      {isSkeletonPhase && activeTaskId && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15 }}
          className="px-6"
        >
          <PlanTaskBox
            chatStore={chatStore}
            taskId={activeTaskId}
            userPrompt={queryGroup.userMessage?.content}
          />
        </motion.div>
      )}
    </motion.div>
  );
};
