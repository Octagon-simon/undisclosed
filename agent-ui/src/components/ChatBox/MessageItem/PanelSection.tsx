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
   * When true the box wears a live ring: a single bright comet sweeps clockwise
   * around the section (top-left -> top-right -> bottom-right -> bottom-left,
   * looping) to show the agent is still working. Off by default so the finished
   * cards stay flat.
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
      // `ml-auto` + `shrink-0`: the meta group rides at the RIGHT end of the row
      // and is never squeezed by the title. Without `shrink-0` the row's flexbox
      // shrinks this box mid-line, which makes its own `flex-wrap` orphan the
      // trailing chevron onto a second line (the "chevron below the stats" bug).
      // The title row wraps as a whole instead, and `ml-auto` keeps the meta
      // right-aligned even on the wrapped line.
      <div className="ml-auto flex shrink-0 flex-wrap items-center justify-end gap-1.5 text-label-xs text-ds-text-neutral-subtle-default">
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
          {/* Faint base ring under the comet so the box keeps a thin edge even
              where the comet isn't. */}
          <div className="absolute inset-0 rounded-lg bg-ds-border-neutral-subtle-default" />
          {/* "This section is live": a slow, multi-colour comet travels clockwise
              around the box (top-left -> top-right -> bottom-right ->
              bottom-left) and loops until the turn ends, the band shifting blue
              -> green -> the rest of the palette as it goes. The gradient + its
              keyframes live in `style/index.css` (`.panel-border-comet`) and use
              `--colors-*` palette tokens; respects prefers-reduced-motion. */}
          <div className="panel-border-comet absolute inset-0 rounded-lg" />
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
              'flex w-full flex-wrap items-center gap-x-2 gap-y-1 text-left outline-none',
              titleClassName
            )}
          >
            {left}
            {right}
          </button>
        ) : (
          <div
            className={cn(
              'flex flex-wrap items-center gap-x-2 gap-y-1',
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
        'bg-ds-bg-neutral-default-default px-2 py-0.5 font-mono text-xs text-ds-text-neutral-subtle-default',
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
