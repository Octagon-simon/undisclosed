// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

/**
 * PanelSection — the shared boxed-section shell for the agent panel revamp
 * (see `panel-revamp.md` and `agent-panel-integration-plan.md`, Phase 0).
 *
 * Every "section" in the revamped panel (Thought Process, Execution Summary,
 * and the future Changed Files card) sits in the same card: a rounded, FLAT box
 * on the neutral default surface (no stroke — the prominent ds panel-border read
 * as a heavy outline, the same reason the picker popover dropped its border).
 * This file owns that box
 * plus the title row (optional icon + label on the left, a metadata slot on the
 * right), so the sections come out pixel-identical instead of each re-declaring
 * the chrome.
 *
 * It also exports the panel's small primitives (`StatusDot`, `Pill`, `Code`,
 * `SectionDivider`, `statusTone`) that the later phases reuse.
 *
 * Colors are semantic `ds-*` tokens only — no literal hex — so the box
 * re-themes with the app (light/dark + Theia).
 */

import { cn } from '@/lib/utils';
import type { ReactNode } from 'react';

export interface PanelSectionProps {
  /** Leading icon rendered inside the title row. */
  icon?: ReactNode;
  /** Title text/nodes (may include a `Pill`). When omitted, no header row renders. */
  title?: ReactNode;
  /** Right end of the title row: stats, badges, chevron, etc. */
  meta?: ReactNode;
  /** When set, the title row becomes a toggle button (`aria-expanded` is wired). */
  onToggle?: () => void;
  /** Disclosure state passed to `aria-expanded` when `onToggle` is set. */
  expanded?: boolean;
  /**
   * When true the box gets an animated, rotating conic-gradient border to show
   * the section is LIVE (the agent is still working). Off by default so the
   * finished cards stay flat.
   */
  active?: boolean;
  /** Extra classes for the outer box (e.g. spacing). */
  className?: string;
  /** Extra classes for the title row. */
  titleClassName?: string;
  children?: ReactNode;
}

export function PanelSection({
  icon,
  title,
  meta,
  onToggle,
  expanded,
  active = false,
  className,
  titleClassName,
  children,
}: PanelSectionProps) {
  const hasTitle = title !== undefined && title !== null;

  const left = (
    <div className="flex min-w-0 items-center gap-1.5 text-sm font-medium text-ds-text-neutral-default-default">
      {icon}
      {title}
    </div>
  );

  const right =
    meta !== undefined && meta !== null ? (
      <div className="flex flex-wrap items-center gap-1.5 text-label-xs text-ds-text-neutral-subtle-default">
        {meta}
      </div>
    ) : null;

  return (
    <section
      className={cn(
        // Flat box: no border. The 1px ds panel-border rendered as a heavy
        // outline around the Thought Process / Execution Summary cards, so the
        // cards now separate by surface + spacing alone. While `active`, the
        // section gets a 1.5px padded shell so the rotating gradient beneath
        // shows as a thin animated ring.
        'relative rounded-lg',
        active && 'p-[1.5px]',
        className
      )}
    >
      {active ? (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 overflow-hidden rounded-lg"
        >
          {/* Rotating conic gradient = "this section is live". Google-palette
              hexes on purpose (like the diff +N/−M greens/reds): a recognizable
              "working" accent that reads on both light and dark. `animate-spin`
              supplies the keyframes; duration is overridden so the sweep is
              calm. Respects prefers-reduced-motion. */}
          <div className="absolute left-1/2 top-1/2 h-[300%] w-[300%] -translate-x-1/2 -translate-y-1/2 animate-spin [animation-duration:3.5s] motion-reduce:animate-none [background:conic-gradient(from_0deg,#4285F4,#EA4335,#FBBC05,#34A853,#4285F4)]" />
        </div>
      ) : null}
      <div
        className={cn(
          'relative bg-ds-bg-neutral-default-default p-3',
          active ? 'rounded-[7px]' : 'rounded-lg'
        )}
      >
      {hasTitle ? (
        onToggle ? (
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={expanded}
            className={cn(
              'flex w-full items-center justify-between gap-2 text-left outline-none',
              titleClassName
            )}
          >
            {left}
            {right}
          </button>
        ) : (
          <div
            className={cn(
              'flex flex-wrap items-center justify-between gap-2',
              titleClassName
            )}
          >
            {left}
            {right}
          </div>
        )
      ) : null}
        {children}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Shared primitives                                                   */
/* ------------------------------------------------------------------ */

/** A dim status dot; `tone` colour comes from the caller's `className`. */
export function StatusDot({
  className,
  pulse = false,
}: {
  className?: string;
  pulse?: boolean;
}) {
  return (
    <span
      aria-hidden
      className={cn(
        'inline-block h-2 w-2 shrink-0 rounded-full',
        pulse && 'animate-pulse',
        className
      )}
    />
  );
}

/** A quiet pill used for metrics / selectors in headers and toolbars. */
export function Pill({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-md border border-ds-border-neutral-subtle-default',
        'bg-ds-bg-neutral-default-default px-2 py-0.5 font-mono text-label-xs text-ds-text-neutral-subtle-default',
        className
      )}
    >
      {children}
    </span>
  );
}

/** Inline code token (`.env.sample`) as used inside the thought process. */
export function Code({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-ds-bg-neutral-muted-default px-1.5 py-0.5 font-mono text-label-xs text-ds-text-information-default-default">
      {children}
    </code>
  );
}

/** A full-width hairline used to separate rows inside a boxed section. */
export function SectionDivider() {
  return <div className="h-px w-full bg-ds-border-neutral-subtle-default" />;
}

/**
 * Git-style file status -> badge tone. Each status keeps its own colour (light
 * and dark) the way the editor gutter shows them:
 *   M = modified (amber) · A = added (green) · D = deleted (red)
 */
export function statusTone(status: 'M' | 'A' | 'D'): 'warning' | 'success' | 'error' {
  if (status === 'A') return 'success';
  if (status === 'D') return 'error';
  return 'warning';
}
