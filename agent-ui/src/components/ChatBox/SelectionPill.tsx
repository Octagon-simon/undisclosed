// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

/**
 * Compact reference to a code selection carried into the agent composer:
 * `[file icon] [ActivityTraceCard.tsx] [L111-154]`.
 *
 * `startLine`/`endLine` are normalized here so the range always reads
 * ascending no matter which direction the user dragged the selection.
 */

import { FILE_ICON_PATHS } from '@/assets/fileIcons.generated';
import { baseName, formatLineRange } from '@/lib/selectionPrompt';
import { cn } from '@/lib/utils';
import { FileText, X } from 'lucide-react';
import type { ReactNode } from 'react';

export interface CodeSelectionRef {
  /** Workspace-relative path. */
  path: string;
  /** 1-based first line. */
  startLine: number;
  /** 1-based last line. */
  endLine: number;
}

export type SelectionPillVariant = 'pill' | 'chip' | 'outline';
export type SelectionPillSize = 'sm' | 'md';

export interface SelectionPillProps {
  path: string;
  startLine: number;
  endLine: number;
  variant?: SelectionPillVariant;
  size?: SelectionPillSize;
  /** Renders a remove button that calls this. */
  onRemove?: () => void;
  /** Makes the whole pill actionable (e.g. reveal the selection). */
  onClick?: () => void;
  className?: string;
}

function FileGlyph({ path }: { path: string }) {
  const ext = baseName(path).includes('.')
    ? baseName(path).split('.').pop()!.toLowerCase()
    : '';
  const entry = FILE_ICON_PATHS[ext];
  if (!entry) {
    return (
      <FileText
        className="size-3.5 shrink-0 text-ds-icon-neutral-subtle-default"
        aria-hidden
      />
    );
  }
  return (
    <svg
      viewBox={entry.viewBox}
      width={14}
      height={14}
      role="img"
      aria-label={entry.title}
      className={cn(
        'shrink-0',
        entry.mono && 'text-ds-icon-neutral-subtle-default'
      )}
    >
      <path
        d={entry.path}
        fill={entry.mono ? 'currentColor' : entry.hex}
      />
    </svg>
  );
}

const SHELL: Record<SelectionPillVariant, string> = {
  pill: 'rounded-full border border-ds-border-neutral-strong-default bg-ds-bg-neutral-default-default',
  chip: 'rounded-md bg-ds-bg-neutral-strong-default',
  outline: 'rounded-md border border-ds-border-neutral-subtle-default',
};

const HEIGHT: Record<SelectionPillSize, string> = {
  sm: 'h-6 gap-1 pl-1.5 pr-2',
  md: 'h-7 gap-1.5 pl-2 pr-2.5',
};

export function SelectionPill({
  path,
  startLine,
  endLine,
  variant = 'pill',
  size = 'sm',
  onRemove,
  onClick,
  className,
}: SelectionPillProps) {
  const name = baseName(path);
  const range = formatLineRange(startLine, endLine);
  const label = `${path} ${range}`;

  const inner: ReactNode = (
    <>
      <FileGlyph path={path} />
      <span className="min-w-0 truncate text-xs font-medium text-ds-text-neutral-default-default">
        {name}
      </span>
      <span
        aria-hidden
        className="h-3 w-px shrink-0 bg-ds-border-neutral-subtle-default"
      />
      <span className="shrink-0 font-mono text-[11px] leading-none text-ds-text-neutral-subtle-default">
        {range}
      </span>
    </>
  );

  const shell = cn(
    'group inline-flex max-w-full items-center transition-colors',
    HEIGHT[size],
    SHELL[variant],
    onClick && 'cursor-pointer hover:border-ds-border-neutral-default-default',
    className
  );

  return (
    <span className="inline-flex max-w-full items-center">
      {onClick ? (
        <button
          type="button"
          onClick={onClick}
          title={label}
          aria-label={`Selection in ${label}`}
          className={cn(shell, 'outline-none')}
        >
          {inner}
        </button>
      ) : (
        <span title={label} className={shell}>
          {inner}
        </span>
      )}
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove ${label}`}
          title="Remove reference"
          className={cn(
            'ml-0.5 flex size-5 shrink-0 items-center justify-center rounded-full text-ds-icon-neutral-subtle-default outline-none',
            'hover:bg-ds-bg-neutral-strong-default hover:text-ds-icon-neutral-default-default'
          )}
        >
          <X className="size-3" aria-hidden />
        </button>
      )}
    </span>
  );
}
