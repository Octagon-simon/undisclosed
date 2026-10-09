// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

/**
 * Execution Summary — spec Section 5 (`panel-revamp.md`), on the real panel.
 *
 * The box is the shared `PanelSection` shell, so it is the same card as the
 * Thought Process above it. The turn's category totals sit at the RIGHT end of
 * the title row ("8 searches / 1 read / 3 modified").
 *
 * Below the title, each KIND of work is its own expandable group:
 *   Codebase Discovery (searches) · Files Read · Files Changed · Commands Run ·
 *   Web Browsing · Project Memory · Connectors.
 * That grouped body is `ActivityCategoryGroups` (ActivityTraceCard) — the exact
 * component the live trace mounts per tool-run, so this section fills in
 * dynamically while the agent works instead of only appearing at the end.
 * Opening a group lists the real activity-trace rows (`ActivityItemRow`):
 * `Read [icon] [filename]` / `Edited [icon] [filename]`, the filename is
 * click-to-open, and the row itself expands to the tool's Request / Response.
 *
 * Data comes from `activityClassifier` (the same `ActivityItem` stream the work
 * log is built from) — no new backend stream. Colors are semantic `ds-*` tokens
 * only — no literal hex.
 */

import {
  summarizeActivities,
  type ActivityItem,
} from '@/lib/activityClassifier';
import { cn } from '@/lib/utils';
import { Zap } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Trans } from 'react-i18next';
import {
  ActivityCategoryGroups,
  METRIC_META,
  METRIC_ORDER,
} from './ActivityTraceCard';
import { PanelSection, Pill } from './PanelSection';
import { formatSplittingElapsed } from './TokenUtils';

/**
 * Re-render every second while `active` so a live "Working for Xs" clock ticks
 * between chat-store updates (the store streams during a turn, but a long tool
 * call can go quiet for a while — the interval keeps the timer honest). Returns
 * `Date.now()` on each render; callers derive the elapsed figure from it.
 */
function useLiveNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [active]);
  return now;
}

export interface ExecutionMetric {
  label: string;
  count: number;
  /** Text-token class for the count, e.g. `text-ds-text-information-default-default`. */
  tone: string;
  /** Plain-English meaning of the category. */
  description?: string;
}

/**
 * Classifier output -> title-row metric list. Counts each category that fired,
 * in a stable order. Returns `[]` when there is nothing meaningful, so the
 * caller can skip the box.
 */
export function executionMetricsFromActivities(
  items: ActivityItem[]
): ExecutionMetric[] {
  const counts = summarizeActivities(items);
  return METRIC_ORDER.filter((category) => counts[category] > 0).map(
    (category) => ({
      label: METRIC_META[category].label,
      count: counts[category],
      tone: METRIC_META[category].tone,
      description: METRIC_META[category].description,
    })
  );
}

/** One stat pill: `N label`, the count coloured by tone. */
function MetricPill({ metric }: { metric: ExecutionMetric }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-ds-border-neutral-subtle-default bg-ds-bg-neutral-subtle-default px-2 py-0.5 text-label-xs text-ds-text-neutral-subtle-default">
      <span className={cn('font-mono font-semibold', metric.tone)}>
        {metric.count}
      </span>
      {metric.label}
    </span>
  );
}

export interface ExecutionSummaryProps {
  /** The turn's classified activity stream (the same source the work log uses). */
  activities: ActivityItem[];
  /**
   * Live turn. Groups start open so progress is visible without a click, and
   * the box wears an animated gradient ring (via `PanelSection active`) so it
   * reads as "the agent is working" at a glance. The finished snapshot is flat.
   */
  running?: boolean;
  /**
   * Epoch ms the turn began (the user message's `createdAt`). While `running`,
   * the title row shows a live "Working for Xs" pill clocked from here, so the
   * card reads as in-progress the way "Worked for Xs" reads as finished. Omit to
   * hide the pill.
   */
  startedAt?: number;
  /** Start every group expanded (stories / preview). */
  defaultOpen?: boolean;
  className?: string;
}

export function ExecutionSummary({
  activities,
  running = false,
  startedAt,
  defaultOpen = false,
  className,
}: ExecutionSummaryProps) {
  const metrics = useMemo(
    () => executionMetricsFromActivities(activities),
    [activities]
  );

  const startedAtValid =
    running && typeof startedAt === 'number' && Number.isFinite(startedAt);
  const now = useLiveNow(Boolean(startedAtValid));
  const workingMs = startedAtValid ? Math.max(0, now - (startedAt as number)) : 0;

  if (!metrics.length) return null;

  return (
    <PanelSection
      icon={
        <Zap
          className="h-4 w-4 text-ds-text-warning-default-default"
          aria-hidden
        />
      }
      title={
        <>
          Execution Summary
          {workingMs > 0 ? (
            // Present-tense twin of the finished "Worked for Xs" pill, so the
            // user watches the turn's clock run instead of a static header.
            <Pill>
              <Trans
                i18nKey="chat.working-for"
                values={{ time: formatSplittingElapsed(workingMs) }}
                components={{ elapsed: <span className="tabular-nums" /> }}
              />
            </Pill>
          ) : null}
        </>
      }
      meta={metrics.map((metric) => (
        <MetricPill key={metric.label} metric={metric} />
      ))}
      active={running}
      className={className}
    >
      {/* Capped + scrollable: a turn that searched and read a lot would
          otherwise push the answer off-screen. */}
      <ActivityCategoryGroups
        activities={activities}
        running={running}
        defaultOpen={defaultOpen}
        className="mt-2.5 max-h-96 overflow-y-auto overscroll-contain"
      />
    </PanelSection>
  );
}
