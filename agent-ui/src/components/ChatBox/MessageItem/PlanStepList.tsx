// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

/**
 * The plan body: one row per step. Presentational only, no header, no box, no
 * state.
 */

import { cn } from '@/lib/utils';
import { TaskStatus, type TaskStatusType } from '@/types/constants';
import { CheckCircle2, Circle, Loader2, XCircle } from 'lucide-react';
import { formatSplittingElapsed } from './TokenUtils';

export interface PlanStep {
  id: string;
  content: string;
  status?: TaskStatusType;
  /** Optional per-step duration (ms); renders right-aligned in mono. */
  durationMs?: number;
}

export interface PlanStepListProps {
  steps: PlanStep[];
  className?: string;
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

export function PlanStepList({ steps, className }: PlanStepListProps) {
  return (
    <ul
      className={cn(
        'm-0 flex max-h-64 list-none flex-col gap-1 overflow-y-auto p-0',
        className
      )}
    >
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
  );
}
