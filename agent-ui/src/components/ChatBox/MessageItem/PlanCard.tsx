// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

/**
 * PlanCard — the INLINE "agent progress" card for the agent panel.
 *
 * This is the plan/todo surface (the decomposed `taskInfo` subtasks) rendered as
 * a normal panel section in the conversation flow, exactly like `ThinkingBlock`
 * and `ExecutionSummary` above/below it: the shared `PanelSection` box, the same
 * title row (icon + label on the left, meta on the right), the same flat surface
 * and the same `active` comet ring while the turn runs.
 *
 * It replaces the OLD sticky `PinnedPlanIndicator`, which floated a centered
 * "Plan · done/total" pill at the top of the scroll viewport. Being pinned meant
 * it never sat with the turn it described; being inline means the user scrolls to
 * the plan with the rest of the turn's work, and the live header ("Agent working"
 * + "Step N of M" + a cyan progress bar) is what tells the user the agent is
 * still going.
 *
 * Data: presentational, takes `steps` (a `TaskInfo[]` is structurally assignable).
 * It is mounted in `UserQueryGroup` — between the Thought Process and the
 * Execution Summary — fed the live task's `taskInfo`, and also renders standalone
 * in Storybook.
 *
 * Layout mirrors the live spec section "Live Agent Activity & Progress":
 *   header  cyan pulse dot + "Agent working" + "Step 3 of 4" + mini bar + "75%"
 *   body    ✓ completed · spinner running (elevated row, "running" pill) ·
 *           ○ queued steps dimmed with a "queued" label
 *
 * Colors are semantic `ds-*` tokens only — no literal hex — so the card re-themes
 * with the app (light/dark + Theia).
 */

import { cn } from '@/lib/utils';
import { TaskStatus, type TaskStatusType } from '@/types/constants';
import { AnimatePresence, motion } from 'framer-motion';
import {
  CheckCircle2,
  ChevronDown,
  Circle,
  ListChecks,
  Loader2,
  XCircle,
} from 'lucide-react';
import { useState } from 'react';
import { PanelSection, Pill } from './PanelSection';
import { formatSplittingElapsed } from './TokenUtils';

export interface PlanStep {
  id: string;
  content: string;
  status?: TaskStatusType;
  /** Optional per-step duration (ms); renders right-aligned in mono. */
  durationMs?: number;
}

export interface PlanCardProps {
  /** The decomposed subtasks, in order. A `TaskInfo[]` satisfies this shape. */
  steps: PlanStep[];
  /** Live turn: shows the "Agent working" header and the active step. */
  running?: boolean;
  /**
   * Wear the animated comet ring. Defaults to `running`. The panel drives this
   * so ONLY one section glows at a time: while a plan exists the ring lives here,
   * and the Execution Summary stays flat; before any plan arrives it is the
   * other way round. See `AgentPanelFull` / `UserQueryGroup`.
   */
  active?: boolean;
  /** Start the checklist expanded. Defaults to open so progress is visible. */
  defaultOpen?: boolean;
  className?: string;
}

/** The pulsing cyan heartbeat shown in the header while the agent works. */
function PulseDot() {
  return (
    <span
      aria-hidden
      className="relative flex h-2.5 w-2.5 shrink-0 items-center justify-center"
    >
      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-ds-icon-information-default-default opacity-60" />
      <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-ds-icon-information-default-default" />
    </span>
  );
}

/** Per-step status glyph: ✓ completed · ✕ failed · spinner running · ○ queued. */
function StepGlyph({ status }: { status?: TaskStatusType }) {
  if (status === TaskStatus.COMPLETED) {
    return (
      <CheckCircle2
        size={16}
        aria-hidden
        className="shrink-0 text-ds-icon-success-default-default"
      />
    );
  }
  if (status === TaskStatus.FAILED) {
    return (
      <XCircle
        size={16}
        aria-hidden
        className="shrink-0 text-ds-icon-error-default-default"
      />
    );
  }
  if (status === TaskStatus.RUNNING) {
    return (
      <Loader2
        size={16}
        aria-hidden
        className="shrink-0 animate-spin text-ds-icon-information-default-default"
      />
    );
  }
  // EMPTY / WAITING / BLOCKED / SKIPPED -> queued
  return (
    <Circle
      size={16}
      aria-hidden
      className="shrink-0 text-ds-icon-neutral-subtle-default"
    />
  );
}

export function PlanCard({
  steps,
  running = false,
  active,
  defaultOpen = true,
  className,
}: PlanCardProps) {
  const [open, setOpen] = useState(defaultOpen);
  // The ring is opt-out-able: default to the live turn, but the panel passes
  // `active={false}` when the Execution Summary owns the ring instead.
  const showRing = active ?? running;

  const total = steps.length;
  if (total === 0) return null; // no plan yet -> no clutter

  const done = steps.filter((s) => s.status === TaskStatus.COMPLETED).length;
  const failed = steps.filter((s) => s.status === TaskStatus.FAILED).length;
  const activeIndex = steps.findIndex((s) => s.status === TaskStatus.RUNNING);
  const pct = Math.round((done / total) * 100);
  const allDone = done === total;

  // Header count: while a step is in flight show "Step N of M" (matches the
  // spec's live header); otherwise show the plain "done/total" tally.
  const countLabel =
    running && activeIndex >= 0
      ? `Step ${activeIndex + 1} of ${total}`
      : `${done}/${total}`;

  return (
    <PanelSection
      icon={
        running ? (
          <PulseDot />
        ) : (
          <ListChecks
            className="h-4 w-4 text-ds-text-information-default-default"
            aria-hidden
          />
        )
      }
      title={
        <>
          {running ? 'Agent working' : 'Plan'}
          <Pill>{countLabel}</Pill>
        </>
      }
      meta={
        <>
          {failed > 0 ? (
            <span className="text-ds-icon-error-default-default">
              {failed} failed
            </span>
          ) : null}
          {/* Mini progress track (spec: ~50px fill + percentage). */}
          <span className="inline-flex h-1.5 w-[50px] overflow-hidden rounded-full bg-ds-bg-neutral-muted-default">
            <span
              className={cn(
                'block h-full rounded-full transition-[width] duration-300',
                allDone
                  ? 'bg-ds-icon-success-default-default'
                  : 'bg-ds-icon-information-default-default'
              )}
              style={{ width: `${pct}%` }}
            />
          </span>
          <span className="font-mono tabular-nums text-ds-text-information-default-default">
            {pct}%
          </span>
          <ChevronDown
            aria-hidden
            className={cn(
              'ml-0.5 h-3.5 w-3.5 shrink-0 text-ds-icon-neutral-subtle-default transition-transform',
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
            {/* Capped + scrollable so a long plan can't push the answer off
                screen; `overscroll-contain` keeps the wheel off the panel. */}
            <ul className="m-0 mt-2.5 flex max-h-64 list-none flex-col gap-1 overflow-y-auto overscroll-contain p-0">
              {steps.map((step, i) => {
                const isRunning = step.status === TaskStatus.RUNNING;
                const isDone = step.status === TaskStatus.COMPLETED;
                const isFailed = step.status === TaskStatus.FAILED;
                const showDuration =
                  typeof step.durationMs === 'number' && step.durationMs > 0;
                return (
                  <li
                    key={step.id || i}
                    className={cn(
                      'flex items-start gap-2.5 rounded-md px-2.5 py-2',
                      // Active step gets the elevated in-flight row.
                      isRunning &&
                        'border border-solid border-ds-border-information-default-default bg-ds-bg-neutral-muted-default'
                    )}
                  >
                    <span className="mt-0.5">
                      <StepGlyph status={step.status} />
                    </span>
                    <span
                      className={cn(
                        'min-w-0 flex-1 text-body-sm leading-relaxed',
                        isFailed
                          ? 'text-ds-icon-error-default-default'
                          : isDone || !isRunning
                            ? 'text-ds-text-neutral-subtle-default'
                            : 'text-ds-text-neutral-default-default'
                      )}
                    >
                      {step.content || `Step ${i + 1}`}
                    </span>
                    {isRunning ? (
                      <span className="shrink-0 rounded border border-solid border-ds-border-information-default-default px-1.5 py-0.5 font-mono text-[10px] leading-none text-ds-text-information-default-default">
                        running
                      </span>
                    ) : null}
                    {showDuration ? (
                      <span className="shrink-0 font-mono text-label-xs tabular-nums text-ds-text-neutral-subtle-default">
                        {formatSplittingElapsed(step.durationMs as number)}
                      </span>
                    ) : !isRunning && !isDone && !isFailed ? (
                      <span className="shrink-0 font-mono text-label-xs text-ds-icon-neutral-subtle-default">
                        queued
                      </span>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </PanelSection>
  );
}
