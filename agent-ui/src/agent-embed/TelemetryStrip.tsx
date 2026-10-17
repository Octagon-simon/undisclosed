// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

/**
 * TelemetryStrip — the panel's quiet status row (spec Section 2, plan Phase 5).
 *
 * It sits directly below the host's native title bar and above the
 * conversation, and carries the panel's only always-on telemetry:
 *   left  — brain liveness (`● Brain live`)
 *   right — the context-window gauge pill (`⚡ 4.42M / 8M (55%)`)
 *
 * Placement: PANEL-LEVEL (mounted once in `AgentEmbedPanel`), not per-turn — the
 * spec places it under the top bar. `TelemetryStripView` is the presentational
 * half (used by the story); `TelemetryStrip` wires the live brain + context
 * hooks into it. Colors are semantic `ds-*` tokens only — no literal hex.
 */

import { BrainStatus } from '@/components/BrainStatus';
import {
  useBrainStatus,
  type BrainState,
} from '@/components/BrainStatus/useBrainStatus';
import { Pill } from '@/components/ChatBox/MessageItem/PanelSection';
import useChatStoreAdapter from '@/hooks/useChatStoreAdapter';
import {
  evaluateContextWindow,
  estimateContextTokens,
  formatTokenCount,
  resolveContextWindow,
} from '@/lib/contextWindow';
import { Zap } from 'lucide-react';
import { useMemo } from 'react';

export interface TelemetryStripViewProps {
  /** Live brain health (drives the dot + label + Restart affordance). */
  brainState: BrainState;
  /** Tokens in the latest request for the active conversation. */
  usedTokens: number;
  /** Resolved context window for the active model. */
  windowTokens: number;
  /** Ask the host to resurrect the brain (shown only when it's down). */
  onRestart: () => void;
}

/** Presentational strip: no stores, no polling — safe to render in isolation. */
export function TelemetryStripView({
  brainState,
  usedTokens,
  windowTokens,
  onRestart,
}: TelemetryStripViewProps) {
  const gauge = evaluateContextWindow(usedTokens, windowTokens);
  const pct = Math.round(gauge.ratio * 100);

  return (
    <div className="flex shrink-0 items-center justify-between gap-2 border-b border-ds-border-neutral-subtle-default px-4 py-2 text-label-xs">
      <span className="inline-flex min-w-0 items-center gap-1.5 text-ds-text-neutral-subtle-default">
        <BrainStatus state={brainState} onRestart={onRestart} />
      </span>
      <Pill>
        <Zap
          className="h-3 w-3 text-ds-text-warning-default-default"
          aria-hidden
        />
        {`${formatTokenCount(gauge.used)} / ${formatTokenCount(
          gauge.window
        )} (${pct}%)`}
      </Pill>
    </div>
  );
}

/**
 * The live context figure the panel shows: the PEAK single-request size across
 * the conversation's tasks (`lastRequestTokens`), falling back to a transcript
 * estimate before anything has run — plus the window resolved from the active
 * model's catalog. Kept in lockstep with `ChatBox/index.tsx`'s
 * `usedTokens`/`contextWindowTokens` (see `lib/contextWindow` for the rationale).
 */
function useContextGauge(): { used: number; window: number } {
  const { chatStore, projectStore } = useChatStoreAdapter();
  const activeProjectId = projectStore.activeProjectId;

  const windowTokens = useMemo(() => {
    const selection = activeProjectId
      ? projectStore.getProjectModel(activeProjectId)
      : null;
    return resolveContextWindow(selection?.model_type || null, {
      providerId: selection?.model_platform || null,
    });
  }, [activeProjectId, projectStore]);

  const used = useMemo(() => {
    const tasks = Object.values(chatStore?.tasks || {}) as Array<{
      lastRequestTokens?: number;
    }>;
    let maxReported = 0;
    for (const tk of tasks) {
      const reported = tk?.lastRequestTokens ?? 0;
      if (reported > maxReported) maxReported = reported;
    }
    if (maxReported > 0) return maxReported;
    const activeTask = chatStore?.activeTaskId
      ? chatStore.tasks[chatStore.activeTaskId]
      : null;
    return estimateContextTokens(activeTask);
  }, [chatStore?.tasks, chatStore?.activeTaskId]);

  return { used, window: windowTokens };
}

/** Live wiring: one brain poller + the active conversation's context gauge. */
export function TelemetryStrip() {
  const { state, restart } = useBrainStatus();
  const { used, window: windowTokens } = useContextGauge();

  return (
    <TelemetryStripView
      brainState={state}
      usedTokens={used}
      windowTokens={windowTokens}
      onRestart={restart}
    />
  );
}
