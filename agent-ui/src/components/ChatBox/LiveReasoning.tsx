// Copyright (c) 2026 Simon Ugorji

import useChatStoreAdapter from '@/hooks/useChatStoreAdapter';
import { useAuthStore } from '@/store/authStore';
import { Brain } from 'lucide-react';
import { useEffect, useRef } from 'react';

/**
 * Live "thinking" surface. Two modes:
 *
 *  1. If the model streams readable reasoning (Action.reasoning deltas
 *     accumulated into the task's `liveReasoning`), render the thoughts as they
 *     arrive.
 *  2. Otherwise, when "show thinking" is on and the model is actively working
 *     but hasn't produced an answer yet, show a lightweight "Thinking…"
 *     indicator. This covers models (e.g. claude-sonnet-5) whose extended
 *     thinking is REDACTED by the provider — the model reasons, but the API
 *     returns no thought text, so there is nothing to print, only to indicate.
 *
 * Cleared once the answer starts streaming or the turn ends.
 */
export function LiveReasoning() {
  const { chatStore } = useChatStoreAdapter();
  const showThinking = useAuthStore((s) => s.showThinking);
  const activeTaskId = chatStore?.activeTaskId as string | undefined;
  const task = activeTaskId ? chatStore?.tasks[activeTaskId] : undefined;
  const reasoning = task?.liveReasoning || '';
  const bodyRef = useRef<HTMLDivElement>(null);
  // Auto-scroll to the newest thinking, but ONLY while the user is already at
  // the bottom. Once they scroll up to read earlier thoughts, stop yanking them
  // back down; resume auto-scroll when they return to the bottom.
  const stickToBottomRef = useRef(true);

  const handleScroll = () => {
    const el = bodyRef.current;
    if (!el) return;
    stickToBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  };

  useEffect(() => {
    const el = bodyRef.current;
    if (el && stickToBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [reasoning]);

  // Is the model working but hasn't started answering? (last message is still
  // the user's, or an agent message with no content yet.) Don't show while
  // waiting on a human prompt.
  const messages = task?.messages || [];
  const last = messages[messages.length - 1];
  const agentHasContent =
    last?.role === 'agent' && !!(last.content && last.content.trim());
  const awaitingHuman = !!task?.activeAsk;
  const thinkingActive =
    showThinking && !!task?.isPending && !agentHasContent && !awaitingHuman;

  if (!reasoning && !thinkingActive) return null;

  return (
    <div className="mx-auto mb-2 w-full max-w-[600px] px-2">
      <div className="rounded-xl border border-solid border-ds-border-neutral-default-default bg-ds-bg-neutral-muted-default px-3 py-2">
        <div className="flex items-center gap-1.5 text-label-xs font-medium text-ds-text-neutral-subtle-default">
          <Brain size={13} className="animate-pulse" aria-hidden />
          Thinking…
        </div>
        {reasoning ? (
          <div
            ref={bodyRef}
            onScroll={handleScroll}
            className="mt-1 max-h-40 overflow-y-auto overscroll-contain whitespace-pre-wrap text-label-xs leading-relaxed text-ds-text-neutral-subtle-default"
          >
            {reasoning}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default LiveReasoning;
