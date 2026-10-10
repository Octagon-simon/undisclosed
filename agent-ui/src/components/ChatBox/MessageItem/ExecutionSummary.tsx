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
 * dynamically while the agent works instead of only appearing at the end. While
 * the turn runs the box starts COLLAPSED (see `running`) so that growing body
 * can't fill the panel; it opens on its own once the turn settles.
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
import { AnimatePresence, motion } from 'framer-motion';
import { ChevronDown, Zap } from 'lucide-react';
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

/**
 * How many stat pills the header shows before folding the rest into a "+N more"
 * chip. The title row must stay ONE line (Execution Summary · Working for ·
 * badges · chevron). A real turn can touch all seven categories (search / read /
 * edit / shell / browser / memory / mcp), and past three pills the meta group
 * starts taking its own line (it always broke once a fifth activity appeared in
 * the 600px story). `grid-flow-col` alone does NOT cap the row, it just makes
 * one long column track and overflows — which is what read as "the grid isn't
 * applying". So the extras fold behind a chip instead. Nothing is lost: opening
 * the section lists every category as its own group with its count, so the
 * hidden stats are one click away.
 */
const MAX_HEADER_PILLS = 3;

/** One stat pill: `N label`, the count coloured by tone. */
function MetricPill({ metric }: { metric: ExecutionMetric }) {
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-md border border-ds-border-neutral-subtle-default bg-ds-bg-neutral-subtle-default px-1 py-0.5 text-label-xs text-ds-text-neutral-subtle-default">
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
   * Live turn. The box starts COLLAPSED: the activity groups below it would
   * otherwise auto-expand and the capped scroll body would trap the wheel until
   * you collapse it by hand. The running card still reads live from its header
   * (the animated gradient ring via `PanelSection active`, plus the "Working for
   * Xs" pill). When the turn settles the box opens so the snapshot is reviewable.
   */
  running?: boolean;
  /**
   * Wear the animated comet ring. Defaults to `running`. The panel sets this
   * false once a Plan card exists, so exactly one section glows at a time: the
   * ring is the summary's only while the task has no plan (todo list) yet.
   */
  active?: boolean;
  /**
   * Epoch ms the turn began (the user message's `createdAt`). While `running`,
   * the title row shows a live "Working for Xs" pill clocked from here, so the
   * card reads as in-progress the way "Worked for Xs" reads as finished. Omit to
   * hide the pill.
   */
  startedAt?: number;
  /** Start the box (and every group) expanded (stories / preview). */
  defaultOpen?: boolean;
  className?: string;
}

export function ExecutionSummary({
  activities,
  running = false,
  active,
  startedAt,
  defaultOpen = false,
  className,
}: ExecutionSummaryProps) {
  const metrics = useMemo(
    () => executionMetricsFromActivities(activities),
    [activities]
  );
  // Cap the header pills so the title row can't wrap; the rest fold into "+N".
  const visibleMetrics = metrics.slice(0, MAX_HEADER_PILLS);
  const hiddenMetrics = metrics.slice(MAX_HEADER_PILLS);

  const showRing = active ?? running;
  const startedAtValid =
    running && typeof startedAt === 'number' && Number.isFinite(startedAt);
  const now = useLiveNow(Boolean(startedAtValid));
  const workingMs = startedAtValid ? Math.max(0, now - (startedAt as number)) : 0;

  // Disclosure state. While the agent is WORKING the box starts collapsed: the
  // activity groups would otherwise auto-expand and the capped scroll body below
  // swallows the wheel until you collapse it by hand. The running card still
  // reads live from its header (comet ring + "Working for Xs"). Once the turn
  // settles we open it, which is where the old always-open box ended up anyway.
  // `defaultOpen` (stories / preview) forces it open outright.
  const [open, setOpen] = useState(defaultOpen || !running);
  useEffect(() => {
    if (!running) setOpen(true);
  }, [running]);

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
      meta={
        <>
          {/* Compact stat badges. This is the flexible zone of the header:
              title · Working for · badges · chevron all sit on ONE row. Past
              `MAX_HEADER_PILLS` badges the extras fold into a "+N more" chip
              (with the full list in its tooltip) instead of spilling onto a
              second row. Opening the section reveals them all as group counts. */}
          <div className="grid grid-flow-col auto-cols-max items-center gap-1">
            {visibleMetrics.map((metric) => (
              <MetricPill key={metric.label} metric={metric} />
            ))}
            {hiddenMetrics.length > 0 ? (
              <span
                title={hiddenMetrics
                  .map((metric) => `${metric.count} ${metric.label}`)
                  .join(' · ')}
                className="inline-flex items-center whitespace-nowrap rounded-md border border-ds-border-neutral-subtle-default bg-ds-bg-neutral-subtle-default px-1 py-0.5 font-mono text-label-xs text-ds-text-neutral-subtle-default"
              >
                +{hiddenMetrics.length} more
              </span>
            ) : null}
          </div>
          <ChevronDown
            aria-hidden
            className={cn(
              'h-3.5 w-3.5 shrink-0 text-ds-icon-neutral-subtle-default transition-transform',
              !open && '-rotate-90'
            )}
          />
        </>
      }
      onToggle={() => setOpen((v) => !v)}
      expanded={open}
      active={showRing}
      className={className}
    >
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            {/* Capped + scrollable: a turn that searched and read a lot would
                otherwise push the answer off-screen. Groups stay collapsed for
                the whole run (`expandWhileRunning={false}`) so manually opening
                this mid-run can't reintroduce the scroll trap. */}
            <ActivityCategoryGroups
              activities={activities}
              running={running}
              defaultOpen={defaultOpen}
              expandWhileRunning={false}
              className="mt-2.5 max-h-96 overflow-y-auto overscroll-contain"
            />
          </motion.div>
        ) : null}
      </AnimatePresence>
    </PanelSection>
  );
}
