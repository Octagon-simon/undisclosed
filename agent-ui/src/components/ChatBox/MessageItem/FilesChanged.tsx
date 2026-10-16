// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
// Portions Copyright 2026 Simon Ugorji. All Rights Reserved.
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========

/**
 * End-of-task "Changed Files" card.
 *
 * A title row (`Changed Files` + file count + `+N/-M` totals) over a SCROLLABLE
 * list of changed files. Each file row is click-to-expand: it reveals that
 * file's real unified diff inline, git-style, with up/down arrows to step
 * through the hunks (`@@` blocks) so a long patch stays navigable.
 *
 * Diffs come from `lib/gitDiff.fetchFileDiff` — `git diff HEAD` for tracked
 * files, `/dev/null` for untracked ones — fetched for every changed file on
 * mount so the `+N/-M` totals are real (the classifier can't always carry
 * them). When the host can't provide a diff (web host, non-repo folder) the row
 * falls back to the classifier's own counts and shows "No diff available".
 *
 * File paths are rendered RELATIVE to the open folder root, never absolute.
 *
 * Removed on purpose (kept out of the render, not the data): the
 * Review/Keep/Revert header actions (shells only, hidden for now), the "Active"
 * featured-file section and its badge, the "Unified diff" toggle, and the
 * "Show all N changed files" drawer row.
 */

import { Badge } from '@/components/ui/badge';
import type { ChangedFile } from '@/lib/activityClassifier';
import { fetchFileDiff } from '@/lib/gitDiff';
import { getOpenFolderRoot } from '@/lib/openFolder';
import { cn } from '@/lib/utils';
import {
  ChevronDown,
  ChevronRight,
  ChevronUp,
  ExternalLink,
  FileText,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';
import { SectionDivider, statusTone } from './PanelSection';

/** `+N` for a file (0 when neither the diff nor the classifier carried stats). */
function addedOf(f: ChangedFile): number {
  return f.diff?.added ?? 0;
}

/** `-M` for a file (0 when neither the diff nor the classifier carried stats). */
function removedOf(f: ChangedFile): number {
  return f.diff?.removed ?? 0;
}

/** Count added/removed lines in a unified patch (`+++`/`---` headers excluded). */
function countPatch(patch: string): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const line of patch.split('\n')) {
    if (line.startsWith('+') && !line.startsWith('+++')) added += 1;
    else if (line.startsWith('-') && !line.startsWith('---')) removed += 1;
  }
  return { added, removed };
}

/**
 * Best-effort git status. The classifier carries no status, so we read the diff
 * shape: additions only looks Added, deletions only looks Deleted, everything
 * else Modified.
 */
function fileStatus(stats: { added: number; removed: number }): 'M' | 'A' | 'D' {
  if (stats.removed === 0 && stats.added > 0) return 'A';
  if (stats.added === 0 && stats.removed > 0) return 'D';
  return 'M';
}

/**
 * The panel reports changed-file paths absolute (or `file://`-prefixed). Strip
 * the scheme and the open folder root so the card shows project-relative paths
 * (`src/foo.ts`), not `/Users/octagon/...`.
 */
function relativeToRoot(filePath: string): string {
  let p = filePath;
  if (p.startsWith('file://')) {
    try {
      p = decodeURIComponent(p.replace(/^file:\/\//, ''));
    } catch {
      p = p.replace(/^file:\/\//, '');
    }
  }
  const root = getOpenFolderRoot();
  if (root) {
    const norm = root.replace(/\/+$/, '');
    if (p === norm) return p.split('/').pop() ?? p;
    if (p.startsWith(`${norm}/`)) p = p.slice(norm.length + 1);
  }
  return p.replace(/^\.\//, '');
}

/**
 * A unified-diff patch as scannable rows: `+` additions (green), `-` deletions
 * (red), `@@` hunk headers (information), context (muted). `diff --git` /
 * `index` header lines are dropped. The body is capped and scrolls; when the
 * patch has hunks, up/down arrows step between them (`@@` blocks).
 */
function DiffView({ patch }: { patch: string }) {
  const lines = useMemo(
    () =>
      patch
        .replace(/\n$/, '')
        .split('\n')
        .filter(
          (l) => !l.startsWith('diff --git ') && !l.startsWith('index ')
        ),
    [patch]
  );

  const hunkPositions = useMemo(
    () =>
      lines.reduce<number[]>(
        (acc, line, i) => (line.startsWith('@@') ? [...acc, i] : acc),
        []
      ),
    [lines]
  );

  const [current, setCurrent] = useState(0);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const hunkRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  // Keep the highlighted hunk in range when the patch shrinks/changes.
  useEffect(() => {
    if (current > hunkPositions.length - 1) {
      setCurrent(Math.max(0, hunkPositions.length - 1));
    }
  }, [hunkPositions.length, current]);

  const goto = useCallback(
    (next: number) => {
      if (!hunkPositions.length) return;
      const clamped = Math.max(0, Math.min(next, hunkPositions.length - 1));
      setCurrent(clamped);
      const el = hunkRefs.current.get(hunkPositions[clamped]);
      const container = containerRef.current;
      // Scroll only the code pane (the container is `relative`, so `offsetTop`
      // is measured from it) — never the surrounding chat.
      if (el && container) {
        container.scrollTo({
          top: Math.max(0, el.offsetTop - 4),
          behavior: 'smooth',
        });
      }
    },
    [hunkPositions]
  );

  return (
    <div className="border-t border-ds-border-neutral-subtle-default bg-ds-bg-neutral-subtle-default">
      {hunkPositions.length ? (
        <div className="flex items-center justify-between gap-2 px-3 py-1.5 text-label-xs text-ds-text-neutral-subtle-default">
          <span>
            {hunkPositions.length} change
            {hunkPositions.length === 1 ? '' : 's'}
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              aria-label="Previous change"
              disabled={current <= 0}
              onClick={() => goto(current - 1)}
              className="flex h-5 w-5 items-center justify-center rounded outline-none transition-colors hover:bg-ds-bg-neutral-muted-default hover:text-ds-text-neutral-default-default focus-visible:outline-none disabled:opacity-40"
            >
              <ChevronUp className="h-3.5 w-3.5" aria-hidden />
            </button>
            <span className="min-w-[3ch] text-center font-mono">
              {current + 1}/{hunkPositions.length}
            </span>
            <button
              type="button"
              aria-label="Next change"
              disabled={current >= hunkPositions.length - 1}
              onClick={() => goto(current + 1)}
              className="flex h-5 w-5 items-center justify-center rounded outline-none transition-colors hover:bg-ds-bg-neutral-muted-default hover:text-ds-text-neutral-default-default focus-visible:outline-none disabled:opacity-40"
            >
              <ChevronDown className="h-3.5 w-3.5" aria-hidden />
            </button>
          </div>
        </div>
      ) : null}
      <div
        ref={containerRef}
        className="relative max-h-72 overflow-auto font-mono text-label-xs leading-relaxed"
      >
        {lines.map((line, i) => {
          const isHunk = line.startsWith('@@');
          const isCurrent = isHunk && hunkPositions[current] === i;
          let tone = 'text-ds-text-neutral-subtle-default';
          if (isHunk) {
            tone = 'text-ds-text-information-default-default opacity-80';
          } else if (line.startsWith('+') && !line.startsWith('+++')) {
            tone = 'text-ds-text-status-completed-default-default';
          } else if (line.startsWith('-') && !line.startsWith('---')) {
            tone = 'text-ds-text-status-error-default-default';
          } else if (line.startsWith('+++') || line.startsWith('---')) {
            tone = 'text-ds-text-neutral-muted-default';
          }
          return (
            <div
              key={`${i}-${line.slice(0, 8)}`}
              ref={
                isHunk
                  ? (el) => {
                      if (el) hunkRefs.current.set(i, el);
                      else hunkRefs.current.delete(i);
                    }
                  : undefined
              }
              className={cn(
                'whitespace-pre px-3',
                tone,
                isCurrent && 'bg-ds-bg-information-subtle-default'
              )}
            >
              {line.length ? line : ' '}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export interface FilesChangedProps {
  files: ChangedFile[];
  /** Sensitive-config / risk summary. When omitted the band is not rendered. */
  riskSummary?: ReactNode;
  /** Open a changed file in the editor (per-row "open externally" affordance). */
  onOpen?: (path: string) => void;
  /**
   * Header actions — shell only until the backend exposes keep/revert. Hidden
   * for now (not rendered); kept on the props so callers/stories stay stable.
   */
  onReviewAll?: () => void;
  onKeepAll?: () => void;
  onRevertAll?: () => void;
  className?: string;
}

export function FilesChanged({
  files,
  riskSummary,
  onOpen,
  className,
}: FilesChangedProps) {
  const paths = files.map((f) => f.path);
  const pathKey = paths.join('\n');

  const [diffs, setDiffs] = useState<Record<string, string | null>>({});
  const [loading, setLoading] = useState(false);
  const [openPath, setOpenPath] = useState<string | null>(null);

  // Fetch every changed file's patch on mount so the +/- totals are real and a
  // row expands instantly. Keyed by the path list so the parent re-rendering a
  // fresh `files` array doesn't re-fetch on every render.
  useEffect(() => {
    if (!pathKey) {
      setDiffs({});
      return;
    }
    let cancelled = false;
    setLoading(true);
    void Promise.all(
      pathKey
        .split('\n')
        .map(async (p) => [p, await fetchFileDiff(p)] as const)
    ).then((entries) => {
      if (cancelled) return;
      setDiffs(Object.fromEntries(entries));
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [pathKey]);

  if (!files.length) return null;

  // The row's patch: the fetched `git diff`, else the classifier's own patch
  // (apply_patch) which is available instantly and in Storybook.
  const fetchedReady = (f: ChangedFile) =>
    Object.prototype.hasOwnProperty.call(diffs, f.path);
  const patchFor = (f: ChangedFile): string | null =>
    diffs[f.path] || f.patch || null;

  // Prefer the patch's stats; fall back to the classifier's.
  const statsOf = (f: ChangedFile) => {
    const patch = patchFor(f);
    if (patch && patch.trim()) return countPatch(patch);
    return { added: addedOf(f), removed: removedOf(f) };
  };

  const additions = files.reduce((n, f) => n + statsOf(f).added, 0);
  const deletions = files.reduce((n, f) => n + statsOf(f).removed, 0);
  const fileLabel = `${files.length} file${files.length === 1 ? '' : 's'}`;

  const rowInteractions = (path: string) => ({
    role: 'button' as const,
    tabIndex: 0,
    'aria-expanded': openPath === path,
    onClick: () => setOpenPath((cur) => (cur === path ? null : path)),
    onKeyDown: (e: KeyboardEvent<HTMLDivElement>) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        setOpenPath((cur) => (cur === path ? null : path));
      }
    },
  });

  return (
    <div
      className={cn(
        'overflow-hidden rounded-lg border border-ds-border-neutral-subtle-default bg-ds-bg-neutral-default-default',
        className
      )}
    >
      {/* Title row: totals on the left. (Review/Keep/Revert hidden for now.) */}
      <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
        <div className="flex items-center gap-2">
          <FileText
            className="h-4 w-4 text-ds-text-neutral-subtle-default"
            aria-hidden
          />
          <span className="text-sm font-semibold text-ds-text-neutral-default-default">
            Changed Files
          </span>
          <span className="rounded border border-ds-border-neutral-subtle-default bg-ds-bg-neutral-subtle-default px-1.5 py-0.5 font-mono text-label-xs text-ds-text-neutral-subtle-default">
            {fileLabel}
          </span>
          <span className="font-mono text-label-xs">
            <span className="text-ds-text-status-completed-default-default">
              +{additions}
            </span>{' '}
            <span className="text-ds-text-status-error-default-default">
              -{deletions}
            </span>
          </span>
        </div>
      </div>

      {/* Housed sensitive-config strip; rendered only when there is a summary. */}
      {riskSummary ? (
        <>
          <SectionDivider />
          <div className="flex flex-wrap items-center gap-1.5 bg-ds-bg-neutral-subtle-default px-3 py-2 text-label-xs text-ds-text-neutral-subtle-default">
            {riskSummary}
          </div>
        </>
      ) : null}

      <SectionDivider />

      {/* Scrollable file list. Each row expands to its own inline diff. */}
      <div className="max-h-72 overflow-auto">
        {files.map((f) => {
          const patch = patchFor(f);
          const stats = statsOf(f);
          const open = openPath === f.path;
          const hasPatch = Boolean(patch && patch.trim());
          return (
            <div
              key={f.path}
              className="border-b border-ds-border-neutral-subtle-default last:border-b-0 cursor-pointer"
            >
              <div
                {...rowInteractions(f.path)}
                title={relativeToRoot(f.path)}
                className={cn(
                  'flex items-center justify-between gap-2 px-3 py-2 text-left outline-none transition-colors hover:bg-ds-bg-neutral-subtle-default focus-visible:outline-none',
                  open && 'bg-ds-bg-neutral-subtle-default'
                )}
              >
                <span className="flex min-w-0 items-center gap-1.5 font-mono text-label-xs text-ds-text-neutral-default-default">
                  <Badge
                    size="xs"
                    variant="secondary"
                    tone={statusTone(fileStatus(stats))}
                  >
                    {fileStatus(stats)}
                  </Badge>
                  <span className="truncate">{relativeToRoot(f.path)}</span>
                </span>
                <span className="flex shrink-0 items-center gap-1.5 font-mono text-label-xs">
                  <span className="text-ds-text-status-completed-default-default">
                    +{stats.added}
                  </span>
                  <span className="text-ds-text-status-error-default-default">
                    -{stats.removed}
                  </span>
                  {onOpen ? (
                    <span
                      role="link"
                      tabIndex={0}
                      aria-label={`Open ${relativeToRoot(f.path)} in editor`}
                      title="Open in editor"
                      onClick={(e) => {
                        e.stopPropagation();
                        onOpen(f.path);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          e.stopPropagation();
                          onOpen(f.path);
                        }
                      }}
                      className="flex items-center text-ds-text-neutral-subtle-default outline-none transition-colors hover:text-ds-text-neutral-default-default focus-visible:outline-none"
                    >
                      <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                    </span>
                  ) : null}
                  <ChevronRight
                    className={cn(
                      'h-3.5 w-3.5 text-ds-text-neutral-subtle-default transition-transform',
                      open && 'rotate-90'
                    )}
                    aria-hidden
                  />
                </span>
              </div>
              {open ? (
                hasPatch ? (
                  <DiffView patch={patch as string} />
                ) : loading && !fetchedReady(f) && !f.patch ? (
                  <div className="border-t border-ds-border-neutral-subtle-default px-3 py-2 text-label-xs text-ds-text-neutral-subtle-default">
                    Loading diff…
                  </div>
                ) : (
                  <div className="border-t border-ds-border-neutral-subtle-default px-3 py-2 text-label-xs text-ds-text-neutral-subtle-default">
                    No diff available.
                  </div>
                )
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
