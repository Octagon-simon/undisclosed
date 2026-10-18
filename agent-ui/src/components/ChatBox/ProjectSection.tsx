// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
// Portions Copyright 2026 Simon Ugorji. All Rights Reserved.
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

import { VanillaChatStore } from '@/store/chatStore';
import { AgentStep } from '@/types/constants';
import { proxyFetchGet, proxyFetchPost } from '@/api/http';
import { motion } from 'framer-motion';
import React from 'react';
import { UserQueryGroup } from './UserQueryGroup';

interface ProjectSectionProps {
  chatId: string;
  chatStore: VanillaChatStore;
  taskId?: string;
  activeQueryId: string | null;
  onQueryActive: (queryId: string | null) => void;
  // onPauseResume: () => void;  // Commented out - temporary not needed
  onSkip: () => void;
  isPauseResumeLoading: boolean;
}

export const ProjectSection = React.forwardRef<
  HTMLDivElement,
  ProjectSectionProps
>(
  (
    {
      chatId,
      chatStore,
      taskId,
      activeQueryId,
      onQueryActive,
      // onPauseResume,  // Commented out - temporary not needed
      onSkip,
      isPauseResumeLoading,
    },
    ref
  ) => {
    // Subscribe to store changes with throttling to prevent excessive re-renders
    const [chatState, setChatState] = React.useState(() =>
      chatStore.getState()
    );

    React.useEffect(() => {
      let timeoutId: NodeJS.Timeout | null = null;
      let latestState: any = null;

      const unsubscribe = chatStore.subscribe((state) => {
        latestState = state;

        // Throttle updates to max once per 100ms
        if (!timeoutId) {
          timeoutId = setTimeout(() => {
            if (latestState) {
              setChatState(latestState);
            }
            timeoutId = null;
          }, 100);
        }
      });

      return () => {
        unsubscribe();
        if (timeoutId) {
          clearTimeout(timeoutId);
          // Apply final state on cleanup
          if (latestState) {
            setChatState(latestState);
          }
        }
      };
    }, [chatStore]);

    const activeTaskId = taskId ?? chatState.activeTaskId;
    const task = activeTaskId ? chatState.tasks[activeTaskId] : null;

    const messages = React.useMemo(() => {
      return task?.messages || [];
    }, [task?.messages]);

    // Memoize grouping to prevent re-creating objects on every render
    const queryGroups = React.useMemo(() => {
      return groupMessagesByQuery(messages);
    }, [messages]);

    // Hydrate persisted turns for THIS task only, matched by the task's OWN
    // user messages (see note after the effect). All turns of a conversation
    // share one chatId dir; loading every turn into every rendered section
    // duplicated earlier turns ("stacking"), while loading only the first turn
    // dropped later ones on reload. Matching a task's full set of user messages
    // handles both a single task that holds several turns AND several tasks that
    // each hold one turn.
    const hydratedSigRef = React.useRef<string | null>(null);
    React.useEffect(() => {
      if (!chatId) return;
      const userMsgs = (task?.messages || []).filter(
        (m: any) => m.role === 'user'
      );
      if (userMsgs.length === 0) return; // wait until we know this task's turns
      const idSet = new Set(userMsgs.map((m: any) => m.id).filter(Boolean));
      const contentSet = new Set(
        userMsgs
          .map((m: any) => (typeof m.content === 'string' ? m.content : null))
          .filter((c: any): c is string => c !== null)
      );
      // A conversation is split into MULTIPLE tasks only during a live session
      // (each follow-up spawns a task). On reload the whole conversation comes
      // back as ONE task (grouped history returns a single task), so that task
      // must render EVERY turn — otherwise only the first turn survives reload.
      // So: single task in this store  -> load ALL turns (renders every query
      // group, one section, no duplication); many tasks -> load only this task's
      // own turns (matched by id/content) to avoid cross-section stacking.
      const taskCount = Object.keys(chatStore.getState().tasks).length;
      const loadAllTurns = taskCount <= 1;
      const sig = `${loadAllTurns ? 'all' : 'own'}|${[...idSet].sort().join(',')}|${[...contentSet].sort().join(',')}`;
      if (hydratedSigRef.current === sig) return;
      hydratedSigRef.current = sig;
      (async () => {
        try {
          const res = await proxyFetchGet(`/api/v1/chat/${encodeURIComponent(chatId)}/turns`);
          if (!Array.isArray(res)) return;
          // Restore the conversation's session mode so the mode chip reflects
          // what it actually ran in (workforce vs single-agent) instead of the
          // default. Persisted with the user turn; any turn carrying it is
          // authoritative for the whole conversation.
          const persistedMode = (res as any[]).find((t) => t?.sessionMode)
            ?.sessionMode;
          if (
            activeTaskId &&
            persistedMode &&
            chatStore.getState().tasks[activeTaskId]?.sessionMode !==
              persistedMode
          ) {
            chatStore
              .getState()
              .setTaskSessionMode(activeTaskId, persistedMode as any);
          }
          const ownTurns = (res as any[]).filter((t) => {
            if (loadAllTurns) return true;
            // Live multi-task: claim ONLY the turn whose persisted queryId is
            // this task's own user-message id. The queryId a turn is stored
            // under IS the user message's id (see enqueueTurnPost callers), and
            // in a live session those ids are stable, so id-matching is exact
            // and 1:1.
            //
            // Do NOT fall back to matching by user-message *content*: two turns
            // can share identical text (e.g. the user types "okay?" twice), and
            // a content match would pull the EARLIER turn's answer into this
            // task — replaying a stale, cached-looking reply keyed to that text.
            // (Reload/replay, where ids are regenerated, takes the loadAllTurns
            // branch above and never reaches here.)
            const tid = t?.queryId ?? t?.userMessage?.id;
            return Boolean(tid && idSet.has(tid));
          });
          if (ownTurns.length === 0) return;
          // Merge: skip messages we already have. Dedup by id AND by
          // (role|content), because the reload replay path
          // (loadProjectFromHistory) re-creates the same messages with FRESH
          // ids — so id-only dedup let every turn appear twice ("stacking").
          // The content key collapses the replay copy and the persisted-turn
          // copy into one.
          const existingIds = new Set((task?.messages || []).map((m: any) => m.id));
          const contentKey = (role: string, content: any) =>
            `${role}\u0000${typeof content === 'string' ? content : JSON.stringify(content ?? '')}`;
          const existingContent = new Set(
            (task?.messages || []).map((m: any) => contentKey(m.role, m.content))
          );
          const merged: any[] = [...(task?.messages || [])];
          let changed = false;
          const takeMessage = (m: any, role: 'user' | 'agent') => {
            if (!m) return;
            const ck = contentKey(role, m.content);
            // A message we already have: fold in the persisted-only fields the
            // live/replayed copy lacks instead of dropping the whole persisted
            // record. The reload replay path re-creates messages with FRESH ids
            // but identical content, so the old "skip if seen" guard silently
            // discarded the persisted `activities` (Execution Summary) and
            // `reasoning`, which is exactly what must survive a reload.
            const existingIdx = merged.findIndex(
              (x: any) =>
                (m.id && x.id === m.id) ||
                contentKey(x.role ?? role, x.content) === ck
            );
            if (existingIdx !== -1) {
              const existing = merged[existingIdx];
              const patch: any = {};
              if (m.activities && !existing.activities)
                patch.activities = m.activities;
              if (m.testRuns && !existing.testRuns)
                patch.testRuns = m.testRuns;
              if (m.reasoning && !existing.reasoning)
                patch.reasoning = m.reasoning;
              if (m.createdAt && !existing.createdAt)
                patch.createdAt = m.createdAt;
              if (m.selections?.length && !existing.selections?.length)
                patch.selections = m.selections;
              if (Object.keys(patch).length) {
                merged[existingIdx] = { ...existing, ...patch };
                changed = true;
              }
              return;
            }
            merged.push({ ...m, role });
            if (m.id) existingIds.add(m.id);
            existingContent.add(ck);
            changed = true;
          };
          for (const turn of ownTurns) {
            takeMessage(turn?.userMessage, 'user');
            // Preserve assistant message order for each turn
            const others = Array.isArray(turn?.otherMessages)
              ? [...turn.otherMessages]
              : [];
            for (const m of others) {
              // Approval outcomes are transient notices, never transcript.
              if (m?.step === AgentStep.APPROVAL_OUTCOME) continue;
              takeMessage(m, 'agent');
            }
          }
          if (activeTaskId && task && changed) {
            // eslint-disable-next-line no-console
            console.debug('[TURNS HYDRATE]', { added: merged.length - task.messages.length });
            chatStore.getState().setMessages(activeTaskId, merged as any);
          }
          // Restore the conversation's cumulative token spend so the sticky
          // counter survives reload. Each persisted turn carries the running
          // total (backend keeps the max), so the largest across turns is the
          // spend so far. setTokens is idempotent and never lowers a live count.
          if (activeTaskId) {
            const persistedTokens = (res as any[]).reduce(
              (mx, t) => Math.max(mx, Number(t?.tokens) || 0),
              0
            );
            if (persistedTokens > 0) {
              chatStore.getState().setTokens(activeTaskId, persistedTokens);
            }
            // Restore the context-window gauge's numerator: the peak single
            // request size the conversation reached, persisted with each turn
            // (backend keeps the max, so take the max across turns too). Without
            // this the gauge reset to 0 on reload and fell back to a coarse
            // transcript estimate that badly under-reports the real context.
            const persistedLastRequest = (res as any[]).reduce(
              (mx, t) => Math.max(mx, Number(t?.lastRequestTokens) || 0),
              0
            );
            if (persistedLastRequest > 0) {
              chatStore
                .getState()
                .setLastRequestTokens(activeTaskId, persistedLastRequest);
            }
          }
        } catch (e) {
          console.warn('Failed to hydrate turns:', e);
        }
      })();
    // Re-run as this task's user messages settle; the sig ref guards against
    // re-hydrating the same set of turns.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [chatId, activeTaskId, task?.messages]);
    if (!activeTaskId || !task) {
      return null;
    }

    return (
      <motion.div
        ref={ref}
        data-turn-id={activeTaskId}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -20 }}
        transition={{ duration: 0.3 }}
        className="relative"
      >
        {/* User Query Groups */}
        <div className="space-y-0">
          {queryGroups.map((group, index) => (
            <UserQueryGroup
              key={`${chatId}-${group.queryId}`}
              chatId={chatId}
              chatStore={chatStore}
              queryGroup={group}
              isActive={activeQueryId === group.queryId}
              onQueryActive={onQueryActive}
              index={index}
              taskId={activeTaskId}
            />
          ))}
        </div>

        {/* The floating "Stop Task" pill was removed: stopping now happens
            inline via the composer's Stop button (send button flips to Stop
            while a task runs). See InputBox / ChatBox inputProps.onStop. */}
      </motion.div>
    );
  }
);

// Add display name for better debugging
ProjectSection.displayName = 'ProjectSection';

// Helper function to group messages by query cycles
function groupMessagesByQuery(messages: any[]) {
  const groups: Array<{
    queryId: string;
    userMessage: any;
    taskMessage?: any;
    otherMessages: any[];
  }> = [];

  let currentGroup: any = null;

  // Track which to_sub_tasks we've already processed to avoid duplicates
  const processedTaskMessages = new Set();

  messages.forEach((message, index) => {
    if (message.role === 'user') {
      // Start a new query group
      if (currentGroup) {
        groups.push(currentGroup);
      }
      currentGroup = {
        queryId: message.id,
        userMessage: message,
        otherMessages: [],
      };
    } else if (message.step === AgentStep.TO_SUB_TASKS) {
      // Task planning message - each should get its own panel

      // Skip if we've already processed this to_sub_tasks
      if (processedTaskMessages.has(message.id)) {
        return;
      }
      processedTaskMessages.add(message.id);

      // Check if any existing group already has this exact taskMessage
      const existingGroupWithTask = groups.find(
        (g) => g.taskMessage && g.taskMessage.id === message.id
      );
      if (existingGroupWithTask) {
        return;
      }

      // If current group doesn't have a task and doesn't already have this task, assign to it
      if (currentGroup && !currentGroup.taskMessage) {
        currentGroup.taskMessage = message;
      } else {
        // Need a new group for this task
        if (currentGroup) {
          groups.push(currentGroup);
        }

        // Find the most recent user message that doesn't have a task yet
        let correspondingUserMessage = null;

        // Look backwards through messages for unassigned user message
        for (let i = index - 1; i >= 0; i--) {
          if (messages[i].role === 'user') {
            // Check if this user message already has a task in existing groups
            const alreadyHasTask = groups.some(
              (g) =>
                g.userMessage &&
                g.userMessage.id === messages[i].id &&
                g.taskMessage
            );

            if (!alreadyHasTask) {
              correspondingUserMessage = messages[i];
              break;
            }
          }
        }

        // Create new group for this to_sub_tasks
        currentGroup = {
          queryId: correspondingUserMessage
            ? correspondingUserMessage.id
            : `task-${message.id}`,
          userMessage: correspondingUserMessage,
          taskMessage: message,
          otherMessages: [],
        };
      }
    } else {
      // Other messages (assistant responses, errors, etc.)
      if (currentGroup) {
        currentGroup.otherMessages.push(message);
      } else {
        // If there is no current user group yet (e.g., the first message is from agent/error),
        // create an anonymous group to ensure the message is rendered.
        currentGroup = {
          queryId: `orphan-${message.id}`,
          userMessage: null,
          otherMessages: [message],
        };
      }
    }
  });

  // Add the last group if it exists
  if (currentGroup) {
    groups.push(currentGroup);
  }

  return groups;
}
