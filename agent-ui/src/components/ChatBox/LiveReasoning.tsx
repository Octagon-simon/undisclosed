// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import useChatStoreAdapter from '@/hooks/useChatStoreAdapter';
import { Brain } from 'lucide-react';
import { useEffect, useRef } from 'react';

/**
 * Live "thinking" block: renders the model's reasoning as it streams in
 * (Action.reasoning deltas accumulated into the task's liveReasoning). Shown
 * only while reasoning is actively arriving; once the turn ends the reasoning is
 * folded onto the final message's collapsible thinking block, so this clears.
 */
export function LiveReasoning() {
  const { chatStore } = useChatStoreAdapter();
  const activeTaskId = chatStore?.activeTaskId as string | undefined;
  const reasoning = activeTaskId
    ? chatStore?.tasks[activeTaskId]?.liveReasoning || ''
    : '';
  const bodyRef = useRef<HTMLDivElement>(null);

  // Keep the newest thinking in view as it streams.
  useEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [reasoning]);

  if (!reasoning) return null;

  return (
    <div className="mx-auto mb-2 w-full max-w-[600px] px-2">
      <div className="rounded-xl border border-solid border-ds-border-neutral-default-default bg-ds-bg-neutral-muted-default px-3 py-2">
        <div className="mb-1 flex items-center gap-1.5 text-label-xs font-medium text-ds-text-neutral-subtle-default">
          <Brain size={13} className="animate-pulse" aria-hidden />
          Thinking…
        </div>
        <div
          ref={bodyRef}
          className="max-h-40 overflow-y-auto whitespace-pre-wrap text-label-xs leading-relaxed text-ds-text-neutral-subtle-default"
        >
          {reasoning}
        </div>
      </div>
    </div>
  );
}

export default LiveReasoning;
