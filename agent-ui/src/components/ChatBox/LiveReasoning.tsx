// Copyright (c) 2026 Simon Ugorji

import useChatStoreAdapter from '@/hooks/useChatStoreAdapter';
import { Brain } from 'lucide-react';
import { useEffect, useRef } from 'react';

/**
 * Live "thinking" block: renders the model's reasoning as it streams in
 * (Action.reasoning deltas accumulated into the task's `liveReasoning`).
 *
 * Shown ONLY while real reasoning is actually arriving — i.e. a reasoning model
 * (e.g. deepseek-reasoner) that returns readable thought text. It does NOT show
 * a speculative "Thinking…" for ordinary turns / non-reasoning models (a plain
 * "How are you" must not flash a thinking block). Providers that redact their
 * thinking (e.g. claude-sonnet-5 returns empty thought text) simply show
 * nothing here — there is nothing to display. Cleared once the turn ends (the
 * reasoning is folded into the message's collapsible "Thought process").
 */
export function LiveReasoning() {
  const { chatStore } = useChatStoreAdapter();
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

  // Only render when the model is ACTUALLY thinking (reasoning text present).
  if (!reasoning) return null;

  return (
    <div className="mx-auto mb-2 w-full max-w-[600px] px-2">
      <div className="rounded-xl border border-solid border-ds-border-neutral-default-default bg-ds-bg-neutral-muted-default px-3 py-2">
        <div className="flex items-center gap-1.5 text-label-xs font-medium text-ds-text-neutral-subtle-default">
          <Brain size={13} className="animate-pulse" aria-hidden />
          Thinking…
        </div>
        <div
          ref={bodyRef}
          onScroll={handleScroll}
          className="mt-1 max-h-40 overflow-y-auto overscroll-contain whitespace-pre-wrap text-label-xs leading-relaxed text-ds-text-neutral-subtle-default"
        >
          {reasoning}
        </div>
      </div>
    </div>
  );
}

export default LiveReasoning;
