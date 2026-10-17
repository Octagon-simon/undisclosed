// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

/**
 * The end-of-turn test run, as the agent panel should show it.
 *
 * A shell-styled card: the command that ran, one row per test with a checkbox
 * that fills in as the run progresses, and a verdict footer (`9 passed in
 * 0.01s`). The rows exist to show *what* was covered, not just the total, so a
 * turn that wrote its own tests reads as evidence instead of a claim.
 *
 * The card is presentational. The agent's shell tool already carries the
 * command and its output; `testRunFromActivity` in `@/lib/testRunParser` turns
 * that pair into these props, so a `shell_exec` that runs a test command feeds
 * the card without a new backend event.
 */

import { Checkbox } from '@/components/ui/checkbox';
import { cn } from '@/lib/utils';
import { AnimatePresence, motion } from 'framer-motion';
import { Check, ChevronDown, Minus, X } from 'lucide-react';
import { useEffect, useId, useMemo, useState } from 'react';

export type TestCaseStatus = 'passed' | 'failed' | 'skipped' | 'pending';

export interface TestCase {
  name: string;
  status: TestCaseStatus;
}

export interface TestRunTotals {
  passed: number;
  failed: number;
  skipped: number;
}

export interface TestRunCardProps {
  /** The exact command, e.g. `.venv/bin/python -m pytest test_app.py`. */
  command: string;
  tests: TestCase[];
  /**
   * Runner totals for output without per-test lines (pytest's default dots).
   * Derived from `tests` when omitted.
   */
  totals?: TestRunTotals;
  /** Wall time as the runner printed it, e.g. `0.01s`. */
  duration?: string;
  /** Small print under the verdict, e.g. `PYTEST OUTPUT FROM THE CAPTURED RUN`. */
  provenance?: string;
  /** The command has not exited yet. */
  running?: boolean;
  /** Tick the test rows in one at a time instead of rendering them settled. */
  animate?: boolean;
  /** Start expanded (default). Fold it to keep the receipt in the turn. */
  defaultOpen?: boolean;
  className?: string;
}

/** Matches the demo film: fast enough to read as collection, slow enough to see. */
const STAGGER_MS = 95;

export function TestRunCard({
  command,
  tests,
  totals,
  duration,
  provenance,
  running = false,
  animate = false,
  defaultOpen = true,
  className,
}: TestRunCardProps) {
  const passed = totals?.passed ?? tests.filter((t) => t.status === 'passed').length;
  const failed = totals?.failed ?? tests.filter((t) => t.status === 'failed').length;
  const total = totals
    ? totals.passed + totals.failed + totals.skipped
    : tests.length;
  const testKey = useMemo(() => tests.map((t) => t.name).join('\n'), [tests]);
  const [revealed, setRevealed] = useState(0);
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();

  useEffect(() => {
    if (!animate) return;
    const timers = [window.setTimeout(() => setRevealed(0), 0)];
    for (let i = 0; i < tests.length; i += 1) {
      timers.push(
        window.setTimeout(() => setRevealed(i + 1), STAGGER_MS * (i + 1))
      );
    }
    return () => timers.forEach((id) => window.clearTimeout(id));
  }, [animate, tests.length, testKey]);

  // Without the stagger every row is settled on the first paint.
  const visible = animate ? Math.min(revealed, tests.length) : tests.length;
  const settled = !running && visible >= tests.length;
  const failedRun = failed > 0;

  return (
    <div
      className={cn(
        'overflow-hidden rounded-lg border border-ds-border-neutral-subtle-default bg-ds-bg-neutral-default-default',
        className
      )}
    >
      {/* The command strip is a raised toolbar, not another helping of the
          card surface: `muted` stays visible on both the card body and the
          panel background in dark mode, where `subtle` collapsed into both. */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={bodyId}
        className={cn(
          'flex w-full items-center justify-between gap-3 bg-ds-bg-neutral-muted-default px-3 py-2 text-left transition-colors hover:bg-ds-bg-neutral-muted-hover',
          open && 'border-b border-ds-border-neutral-subtle-default'
        )}
      >
        {/* `code` carries a global #1a1a1a fill, which made the light-mode
            command black-on-black. Neutralise it here; the strip owns its bg. */}
        <code className="m-0 flex min-w-0 items-center gap-1.5 rounded-none bg-transparent p-0 font-mono text-label-xs">
          <span className="text-ds-text-status-completed-default-default">$</span>
          <span
            className="truncate text-ds-text-neutral-default-default"
            title={command}
          >
            {command}
          </span>
          {running ? (
            <span
              aria-hidden
              className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-ds-text-status-completed-default-default"
            />
          ) : null}
        </code>

        <span className="flex shrink-0 items-center gap-2">
          {settled && !open ? (
            <span
              className={cn(
                'flex items-center gap-1 font-mono text-label-xs',
                failedRun
                  ? 'text-ds-text-status-error-default-default'
                  : 'text-ds-text-status-completed-default-default'
              )}
            >
              {failedRun ? (
                <X
                  className="h-3.5 w-3.5"
                  style={{ color: 'var(--ds-text-status-error-default-default)' }}
                  aria-hidden
                />
              ) : (
                <Check
                  className="h-3.5 w-3.5"
                  style={{
                    color: 'var(--ds-text-status-completed-default-default)',
                  }}
                  aria-hidden
                />
              )}
              {failedRun ? `${failed} failed` : `${passed} passed`}
              {duration ? (
                <span className="text-ds-text-neutral-subtle-default">
                  in {duration}
                </span>
              ) : null}
            </span>
          ) : (
            <span className="font-mono text-label-xs tracking-[0.16em] text-ds-text-status-completed-default-default">
              {total === 1 ? `${total} TEST` : `${total} TESTS`}
            </span>
          )}
          <ChevronDown
            aria-hidden
            className={cn(
              'h-3.5 w-3.5 shrink-0 text-ds-icon-neutral-subtle-default transition-transform',
              !open && '-rotate-90'
            )}
          />
        </span>
      </button>

      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            id={bodyId}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            {tests.length ? (
              // Capped like the Execution Summary's groups: a 40-test file
              // must not push the answer off-screen. No `overscroll-contain`,
              // so the wheel chains to the panel once the roster hits its edge.
              <ul className="max-h-96 overflow-y-auto py-1">
                {tests.map((test, index) => {
                  const done = index < visible;
                  const failedRow = done && test.status === 'failed';
                  const skippedRow = done && test.status === 'skipped';
                  return (
                    <li
                      key={test.name}
                      className="flex h-9 items-center gap-2.5 px-3 font-mono text-label-xs"
                    >
                      {failedRow ? (
                        <span
                          className="flex h-4 w-4 shrink-0 items-center justify-center rounded border border-ds-border-status-error-default-default"
                          style={{
                            backgroundColor:
                              'var(--ds-bg-status-error-default-active)',
                          }}
                        >
                          <X
                            className="h-3 w-3"
                            style={{ color: 'white' }}
                            aria-hidden
                          />
                        </span>
                      ) : skippedRow ? (
                        <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded border border-ds-border-neutral-default-default text-ds-text-neutral-subtle-default">
                          <Minus className="h-3 w-3" aria-hidden />
                        </span>
                      ) : (
                        <Checkbox
                          checked={done && test.status === 'passed'}
                          disabled
                          aria-label={`${test.name} ${test.status}`}
                        />
                      )}
                      <span
                        className={cn(
                          'truncate transition-colors',
                          done
                            ? 'text-ds-text-neutral-default-default'
                            : 'text-ds-text-neutral-subtle-default',
                          skippedRow && 'line-through opacity-60'
                        )}
                      >
                        {test.name}
                      </span>
                    </li>
                  );
                })}
              </ul>
            ) : null}

            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-t border-ds-border-neutral-subtle-default px-3 py-2.5">
              {settled ? (
                <>
                  <span
                    className={cn(
                      'text-[28px] font-medium leading-none tracking-tight',
                      failedRun
                        ? 'text-ds-text-status-error-default-default'
                        : 'text-ds-text-status-completed-default-default'
                    )}
                  >
                    {failedRun ? failed : passed}
                  </span>
                  <span className="text-sm font-medium text-ds-text-neutral-default-default">
                    {failedRun ? 'failed' : 'passed'}
                  </span>
                  {duration ? (
                    <span className="font-mono text-label-xs text-ds-text-neutral-subtle-default">
                      in {duration}
                    </span>
                  ) : null}
                  {provenance ? (
                    <span className="ml-auto font-mono text-label-xs tracking-[0.12em] text-ds-text-neutral-subtle-default">
                      {provenance}
                    </span>
                  ) : null}
                </>
              ) : (
                <span className="font-mono text-label-xs text-ds-text-neutral-subtle-default">
                  {running ? 'running' : 'collecting'}
                  {tests.length ? (
                    <span className="ml-1.5 text-ds-text-neutral-default-default">
                      {visible}/{tests.length}
                    </span>
                  ) : null}
                </span>
              )}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
