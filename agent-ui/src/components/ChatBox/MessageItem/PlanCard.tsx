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
import { TaskStatus } from '@/types/constants';
import { AnimatePresence, motion } from 'framer-motion';
import { ChevronDown, ListChecks } from 'lucide-react';
import { useState } from 'react';
import { PanelSection, Pill } from './PanelSection';
import { PlanStepList, type PlanStep } from './PlanStepList';

export type { PlanStep };

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
  /**
   * Freeze the live comet ring (keep it, stop its sweep) while the agent is
   * blocked on a human question. See `PanelSection.paused`.
   */
  paused?: boolean;
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

export function PlanCard({
  steps,
  running = false,
  active,
  paused = false,
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

  const planTooltip =
    running && activeIndex >= 0
      ? `Agent working: step ${activeIndex + 1} of ${total}`
      : `Plan: ${done} of ${total} step${total === 1 ? '' : 's'} done${
          failed ? `, ${failed} failed` : ''
        }`;

  return (
    <PanelSection
      tooltip={planTooltip}
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
      paused={paused}
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
                screen. We deliberately do NOT set `overscroll-contain`: that
                trapped the wheel inside the list at its top/bottom, so a user
                trying to scroll up to earlier chat stayed stuck here. Leaving
                the browser default (`auto`) chains the wheel to the panel once
                this list hits its cap, so scrolling past the plan scrolls the
                conversation above it. */}
            <PlanStepList steps={steps} className="mt-2.5" />
          </motion.div>
        ) : null}
      </AnimatePresence>
    </PanelSection>
  );
}
