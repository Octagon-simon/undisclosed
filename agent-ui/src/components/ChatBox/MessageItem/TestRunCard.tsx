// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

/**
 * The end-of-turn test run, as the agent panel should show it.
 *
 * A shell-styled card: the command that ran, the test files the runner named,
 * one row per test with a checkbox that fills in as the run progresses, and a
 * verdict footer (`9 passed in 0.01s`). The rows exist to show *what* was
 * covered, not just the total, so a turn that wrote its own tests reads as
 * evidence instead of a claim.
 *
 * The card is presentational. The agent's shell tool already carries the
 * command and its output; `testRunFromActivity` in `@/lib/testRunParser` turns
 * that pair into these props, so a `shell_exec` that runs a test command feeds
 * the card without a new backend event.
 */

import { Checkbox } from "@/components/ui/checkbox";
import { splitPathTail } from "@/lib/pathLabel";
import { cn } from "@/lib/utils";
import { AnimatePresence, motion } from "framer-motion";
import { Check, ChevronDown, Copy, Minus, X } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";

export type TestCaseStatus = "passed" | "failed" | "skipped" | "pending";

export interface TestCase {
  name: string;
  status: TestCaseStatus;
}

/**
 * One test file's verdict. Vitest prints these as `✓ path (3 tests) 23ms`,
 * jest as `PASS path`, and pytest groups its `path::test` rows by file.
 */
export interface TestFileResult {
  path: string;
  status: TestCaseStatus;
  passed?: number;
  failed?: number;
  skipped?: number;
  duration?: string;
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
  /** Per-file verdicts, when the runner prints a file roster. */
  files?: TestFileResult[];
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
  /**
   * Native hover tooltip and accessible name for the header. Defaults to a
   * sentence built from the totals, so hover alone says "test run, 9 tests,
   * 9 passed in 0.01s" instead of leaving the card anonymous.
   */
  tooltip?: string;
  className?: string;
}

/** Matches the demo film: fast enough to read as collection, slow enough to see. */
const STAGGER_MS = 95;

/** How long the copy button shows its check before returning to the icon. */
const COPIED_RESET_MS = 1600;

/** Clipboard API first; a Theia webview can deny it, so fall back to execCommand. */
async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  }
}

/** Right-aligned per-file counts, or the file's duration when it has no counts. */
function fileDetail(file: TestFileResult): string {
  const parts: string[] = [];
  if (file.failed) parts.push(`${file.failed} failed`);
  if (file.passed) parts.push(`${file.passed} passed`);
  if (file.skipped) parts.push(`${file.skipped} skipped`);
  return parts.length ? parts.join(", ") : (file.duration ?? "");
}

export function TestRunCard({
  command,
  tests = [],
  files = [],
  totals,
  duration,
  provenance,
  running = false,
  animate = false,
  defaultOpen = true,
  tooltip,
  className,
}: TestRunCardProps) {
  // Without per-test rows the file rows are the only counts available (jest,
  // and pytest without -v), so the footer reads those instead of reporting 0.
  const fileTotals = files.reduce(
    (acc, file) => ({
      passed: acc.passed + (file.passed ?? (file.status === "passed" ? 1 : 0)),
      failed: acc.failed + (file.failed ?? (file.status === "failed" ? 1 : 0)),
      skipped:
        acc.skipped + (file.skipped ?? (file.status === "skipped" ? 1 : 0)),
    }),
    { passed: 0, failed: 0, skipped: 0 },
  );
  const counts =
    totals ??
    (tests.length > 0
      ? {
          passed: tests.filter((t) => t.status === "passed").length,
          failed: tests.filter((t) => t.status === "failed").length,
          skipped: tests.filter((t) => t.status === "skipped").length,
        }
      : fileTotals);
  const passed = counts.passed;
  const failed = counts.failed;
  const total = totals
    ? totals.passed + totals.failed + totals.skipped
    : tests.length > 0
      ? tests.length
      : files.length;
  const unitNoun = tests.length > 0 ? "test" : "file";
  // Files render above tests and tick in first, so the stagger walks both lists.
  const unitCount = files.length + tests.length;
  const testKey = useMemo(
    () =>
      [
        ...files.map((f) => `f:${f.path}`),
        ...tests.map((t) => `t:${t.name}`),
      ].join("\n"),
    [files, tests],
  );
  const [revealed, setRevealed] = useState(0);
  const [open, setOpen] = useState(defaultOpen);
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<number | null>(null);
  const bodyId = useId();

  useEffect(
    () => () => {
      if (copyTimer.current) window.clearTimeout(copyTimer.current);
    },
    [],
  );

  const handleCopy = async () => {
    if (!(await copyToClipboard(command))) return;
    setCopied(true);
    if (copyTimer.current) window.clearTimeout(copyTimer.current);
    copyTimer.current = window.setTimeout(
      () => setCopied(false),
      COPIED_RESET_MS,
    );
  };

  useEffect(() => {
    if (!animate) return;
    const timers = [window.setTimeout(() => setRevealed(0), 0)];
    for (let i = 0; i < unitCount; i += 1) {
      timers.push(
        window.setTimeout(() => setRevealed(i + 1), STAGGER_MS * (i + 1)),
      );
    }
    return () => timers.forEach((id) => window.clearTimeout(id));
  }, [animate, unitCount, testKey]);

  // Without the stagger every row is settled on the first paint.
  const visible = animate ? Math.min(revealed, unitCount) : unitCount;
  const settled = !running && visible >= unitCount;
  const failedRun = failed > 0;

  const verdictText = failedRun
    ? `${failed} failed${passed ? `, ${passed} passed` : ""}`
    : `${passed} passed`;
  const cardTooltip =
    tooltip ??
    (total
      ? `Test run: ${total} ${unitNoun}${total === 1 ? "" : "s"}, ${
          settled
            ? `${verdictText}${duration ? ` in ${duration}` : ""}`
            : running
              ? "running now"
              : "collecting results"
        }`
      : "Test run: the command the agent used to check its changes");

  return (
    <div
      className={cn(
        "overflow-hidden rounded-lg border border-ds-border-neutral-subtle-default bg-ds-bg-neutral-default-default",
        className,
      )}
    >
      {/* The command strip is a raised toolbar, not another helping of the
          card surface: `muted` stays visible on both the card body and the
          panel background in dark mode, where `subtle` collapsed into both. */}
      {/* No hover fill here: the neighbouring sections have none, and in the
          Theia embed the theme maps the hover token to its own selection
          colour, which read as a green wash on this card only. */}
      <div
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex cursor-pointer items-center gap-1 bg-ds-bg-neutral-muted-default pl-3 pr-1.5",
          open && "border-b border-ds-border-neutral-subtle-default",
        )}
      >
        <button
          type="button"
          onClick={(e) => {
            // The strip itself is clickable; keep this from toggling twice.
            e.stopPropagation();
            setOpen((v) => !v);
          }}
          aria-expanded={open}
          aria-controls={bodyId}
          aria-label={cardTooltip}
          title={cardTooltip}
          className="flex min-w-0 flex-1 items-center gap-1.5 py-2 text-left outline-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ds-ring-brand-default-focus"
        >
          {/* `code` carries a global #1a1a1a fill, which made the light-mode
            command black-on-black. Neutralise it here; the strip owns its bg. */}
          <code className="m-0 flex min-w-0 flex-1 items-center gap-1.5 rounded-none bg-transparent p-0 font-mono text-label-xs">
            <span className="text-ds-text-status-completed-default-default">
              $
            </span>
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
        </button>
        <button
          type="button"
          onClick={(e) => {
            // Copy is about the command, so it sits at the ellipsis and must
            // not fold the card.
            e.stopPropagation();
            void handleCopy();
          }}
          aria-label={copied ? "Test command copied" : "Copy test command"}
          title={copied ? "Copied" : "Copy command"}
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded opacity-60 transition-opacity hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-ring-brand-default-focus"
        >
          {copied ? (
            <Check
              className="h-3.5 w-3.5"
              style={{
                color: "var(--ds-text-status-completed-default-default)",
              }}
              aria-hidden
            />
          ) : (
            <Copy className="h-3.5 w-3.5" aria-hidden />
          )}
        </button>
        <span role="status" className="sr-only">
          {copied ? "Test command copied to clipboard" : ""}
        </span>
        <span className="flex shrink-0 items-center gap-2">
          {settled && !open ? (
            <span
              className={cn(
                "flex items-center gap-1 font-mono text-label-xs",
                failedRun
                  ? "text-ds-text-status-error-default-default"
                  : "text-ds-text-status-completed-default-default",
              )}
            >
              {failedRun ? (
                <X
                  className="h-3.5 w-3.5"
                  style={{
                    color: "var(--ds-text-status-error-default-default)",
                  }}
                  aria-hidden
                />
              ) : (
                <Check
                  className="h-3.5 w-3.5"
                  style={{
                    color: "var(--ds-text-status-completed-default-default)",
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
              {`${total} ${unitNoun.toUpperCase()}${total === 1 ? "" : "S"}`}
            </span>
          )}
          <ChevronDown
            aria-hidden
            className={cn(
              "h-3.5 w-3.5 shrink-0 text-ds-icon-neutral-subtle-default transition-transform",
              !open && "-rotate-90",
            )}
          />
        </span>
      </div>

      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            id={bodyId}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="overflow-hidden"
          >
            {unitCount ? (
              // Capped like the Execution Summary's groups: a 40-test file
              // must not push the answer off-screen. No `overscroll-contain`,
              // so the wheel chains to the panel once the roster hits its edge.
              <ul className="max-h-96 overflow-y-auto py-1 px-0">
                {files.map((file, index) => {
                  const done = index < visible;
                  const failedFile = done && file.status === "failed";
                  const skippedFile = done && file.status === "skipped";
                  const detail = fileDetail(file);
                  const label = splitPathTail(file.path);
                  return (
                    <li
                      key={file.path}
                      className="flex h-9 items-center gap-2.5 px-3 font-mono text-label-xs"
                    >
                      {failedFile ? (
                        <span
                          className="flex h-4 w-4 shrink-0 items-center justify-center rounded border border-ds-border-status-error-default-default"
                          style={{
                            backgroundColor:
                              "var(--ds-bg-status-error-default-active)",
                          }}
                        >
                          <X
                            className="h-3 w-3"
                            style={{ color: "white" }}
                            aria-hidden
                          />
                        </span>
                      ) : skippedFile ? (
                        <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded border border-ds-border-neutral-default-default text-ds-text-neutral-subtle-default">
                          <Minus className="h-3 w-3" aria-hidden />
                        </span>
                      ) : (
                        <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                          <Check
                            className="h-3.5 w-3.5"
                            style={{
                              color:
                                "var(--ds-text-status-completed-default-default)",
                            }}
                            aria-hidden
                          />
                        </span>
                      )}
                      <span
                        title={file.path}
                        className={cn(
                          "flex min-w-0 flex-1 items-baseline transition-colors",
                          done
                            ? "text-ds-text-neutral-default-default"
                            : "text-ds-text-neutral-subtle-default",
                          skippedFile && "line-through opacity-60",
                        )}
                      >
                        {label.head ? (
                          <span className="min-w-0 truncate">{label.head}</span>
                        ) : null}
                        <span className="max-w-full shrink-0 truncate">
                          {label.tail}
                        </span>
                      </span>
                      {detail ? (
                        <span className="shrink-0 text-ds-text-neutral-subtle-default">
                          {detail}
                        </span>
                      ) : null}
                    </li>
                  );
                })}
                {files.length && tests.length ? (
                  <li
                    aria-hidden
                    className="mx-3 my-1 h-px bg-ds-border-neutral-subtle-default"
                  />
                ) : null}
                {tests.map((test, index) => {
                  const done = files.length + index < visible;
                  const failedRow = done && test.status === "failed";
                  const skippedRow = done && test.status === "skipped";
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
                              "var(--ds-bg-status-error-default-active)",
                          }}
                        >
                          <X
                            className="h-3 w-3"
                            style={{ color: "white" }}
                            aria-hidden
                          />
                        </span>
                      ) : skippedRow ? (
                        <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded border border-ds-border-neutral-default-default text-ds-text-neutral-subtle-default">
                          <Minus className="h-3 w-3" aria-hidden />
                        </span>
                      ) : (
                        <Checkbox
                          checked={done && test.status === "passed"}
                          disabled
                          aria-label={`${test.name} ${test.status}`}
                        />
                      )}
                      <span
                        className={cn(
                          "truncate transition-colors",
                          done
                            ? "text-ds-text-neutral-default-default"
                            : "text-ds-text-neutral-subtle-default",
                          skippedRow && "line-through opacity-60",
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
                      "text-lg font-medium leading-none tracking-tight",
                      failedRun
                        ? "text-ds-text-status-error-default-default"
                        : "text-ds-text-status-completed-default-default",
                    )}
                  >
                    {failedRun ? failed : passed}
                  </span>
                  <span className="text-sm font-medium text-ds-text-neutral-default-default">
                    {failedRun ? "failed" : "passed"}
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
                  {running ? "running" : "collecting"}
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
