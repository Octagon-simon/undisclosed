// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
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
 * Compact Claude-Code-style activity trace: consecutive tool calls inside an
 * agent's timeline collapse into one "Explored 2 files, 1 search" group
 * instead of a flat always-expanded row list. Gated behind
 * `isActivityTraceEnabled()`; `TaskWorkLogAccordion` renders this in place
 * of the per-item message/tool rows when the flag is on, unchanged when off.
 */

import {
  InlineMessageRow,
  type TimelineItem,
} from '@/components/ChatBox/MessageItem/workLogTimeline';
import { FILE_ICON_PATHS } from '@/assets/fileIcons.generated';
import ShinyText from '@/components/ui/ShinyText/ShinyText';
import { MarkDown } from '@/components/WorkFlow/MarkDown';
import {
  buildActivityRenderEntries,
  type ActivityCategory,
  type ActivityItem,
} from '@/lib/activityClassifier';
import { cn } from '@/lib/utils';
import { AnimatePresence, motion } from 'framer-motion';
import { useHost } from '@/host';
import {
  Brain,
  ChevronDown,
  ChevronRight,
  FileText,
  Globe,
  Image as ImageIcon,
  Pencil,
  Plug,
  Search,
  Terminal,
  type LucideIcon,
} from 'lucide-react';
import { memo, useMemo, useState } from 'react';

/**
 * Real per-language SVG logo, generated from Simple Icons into
 * `fileIcons.generated.ts` (see `scripts/fetch-file-icons.mjs`).
 *
 * Brand logos belong to their respective owners; we bundle the path data only,
 * so nothing is fetched at runtime. See `fileIcons.LICENSE.md`.
 */
const FileSvgIcon = memo(function FileSvgIcon({
  entry,
}: {
  entry: {
    title: string;
    hex: string;
    mono?: boolean;
    path: string;
    viewBox: string;
  };
}) {
  // `mono` entries are brands whose own mark is a near-black solid (JSON,
  // Markdown, Rust…), plus mid/dark brand colors that no longer read on a dark
  // surface once the light-mode background flips. Those render in
  // `currentColor`, which makes dark mode work by construction instead of a
  // per-icon `filter: invert(1)` hack. Saturated colors that read on both
  // themes (TypeScript blue, Go cyan, Python blue…) keep their brand hex.
  const fill = entry.mono ? 'currentColor' : entry.hex;
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
      <path d={entry.path} fill={fill} />
    </svg>
  );
});

/**
 * Split a file path into a muted parent dir (last ≤2 segments, prefixed with
 * "…/" when deeper) + the basename, so file rows read like Antigravity's
 * "…/components/ProjectSection.tsx" with the filename emphasized.
 */
function splitPathForDisplay(p: string): { dir: string; base: string } {
  const clean = (p || '').replace(/\/+$/, '');
  const parts = clean.split(/[\\/]/).filter(Boolean);
  if (parts.length <= 1) return { dir: '', base: clean };
  const base = parts[parts.length - 1];
  const dirParts = parts.slice(0, -1);
  const tail = dirParts.slice(-2);
  const dir = (dirParts.length > tail.length ? '…/' : '') + tail.join('/') + '/';
  return { dir, base };
}

/**
 * Legacy fallback badge: a small rounded square with a short label in the
 * language's brand color. Used only for extensions with no brand mark upstream
 * (txt, rst, java, .m/.mm, .proto) and for anything unknown.
 */
// color = the outline/label color. ts vs tsx (and js vs jsx) are distinct.
const FILE_BADGE: Record<string, { label: string; color: string }> = {
  ts: { label: 'TS', color: '#3178c6' },
  tsx: { label: 'TSX', color: '#4fb0d8' },
  js: { label: 'JS', color: '#c9a800' },
  jsx: { label: 'JSX', color: '#3f9ec4' },
  mjs: { label: 'MJS', color: '#c9a800' },
  cjs: { label: 'CJS', color: '#c9a800' },
  py: { label: 'PY', color: '#3776ab' },
  json: { label: '{ }', color: '#a68f2a' },
  md: { label: 'MD', color: '#519aba' },
  mdx: { label: 'MDX', color: '#519aba' },
  txt: { label: 'TXT', color: '#6b7280' },
  rst: { label: 'RST', color: '#6b7280' },
  css: { label: 'CSS', color: '#2965f1' },
  scss: { label: 'SCSS', color: '#c6538c' },
  less: { label: 'LESS', color: '#2b5b8c' },
  html: { label: '<>', color: '#e34c26' },
  vue: { label: 'VUE', color: '#41b883' },
  svelte: { label: 'SV', color: '#ff3e00' },
  go: { label: 'GO', color: '#00add8' },
  rs: { label: 'RS', color: '#b07a56' },
  java: { label: 'JAVA', color: '#e76f00' },
  kt: { label: 'KT', color: '#a97bff' },
  rb: { label: 'RB', color: '#cc342d' },
  php: { label: 'PHP', color: '#777bb4' },
  c: { label: 'C', color: '#6b7280' },
  cpp: { label: 'C++', color: '#00599c' },
  cc: { label: 'C++', color: '#00599c' },
  h: { label: 'H', color: '#6b7280' },
  sh: { label: 'SH', color: '#4eaa25' },
  bash: { label: 'SH', color: '#4eaa25' },
  zsh: { label: 'SH', color: '#4eaa25' },
  sql: { label: 'SQL', color: '#9a8f8f' },
  yml: { label: 'YML', color: '#cb171e' },
  yaml: { label: 'YAML', color: '#cb171e' },
  toml: { label: 'TOML', color: '#9c4221' },
  xml: { label: 'XML', color: '#f1662a' },
};

const IMAGE_EXTS = new Set([
  'png',
  'jpg',
  'jpeg',
  'gif',
  'svg',
  'webp',
  'ico',
  'avif',
  'bmp',
]);

function badgeFor(path: string): { label: string; color: string } {
  const base = (path.split(/[\\/]/).pop() || path).toLowerCase();
  if (base === 'package.json' || base === 'package-lock.json')
    return { label: 'npm', color: '#cb3837' };
  if (base.startsWith('readme')) return { label: 'MD', color: '#519aba' };
  if (base.startsWith('dockerfile')) return { label: 'DK', color: '#2496ed' };
  if (base.startsWith('.env')) return { label: 'ENV', color: '#b7a100' };
  const ext = base.includes('.') ? base.split('.').pop()! : '';
  return (
    FILE_BADGE[ext] ?? {
      label: ext ? ext.slice(0, 4).toUpperCase() : '•',
      color: '#6b7280',
    }
  );
}

function FileTypeIcon({ path }: { path: string }) {
  const ext = path.split('.').pop()?.toLowerCase() ?? '';
  if (IMAGE_EXTS.has(ext)) {
    return (
      <ImageIcon
        size={14}
        aria-hidden
        className="shrink-0 text-ds-icon-neutral-subtle-default"
      />
    );
  }
  // Prefer a real language logo when we have one; the chip stays for the
  // extensions listed in FILE_ICON_FALLBACK_EXTENSIONS (and anything unknown).
  const icon = FILE_ICON_PATHS[ext];
  if (icon) return <FileSvgIcon entry={icon} />;
  const { label, color } = badgeFor(path);
  // Outlined (not a solid block): transparent fill, colored border + label.
  return (
    <span
      aria-hidden
      style={{ borderColor: color, color }}
      className="flex h-[15px] min-w-[15px] shrink-0 items-center justify-center rounded-[3px] border border-solid bg-transparent px-[3px] font-mono text-[8px] font-bold leading-none"
    >
      {label}
    </span>
  );
}

const CONTENT_EASE: [number, number, number, number] = [0.32, 0.72, 0, 1];
const HEIGHT_MOTION = {
  height: { duration: 0.22, ease: CONTENT_EASE },
  opacity: { duration: 0.16, ease: CONTENT_EASE },
} as const;

/**
 * Category -> leading icon. Exported so the Execution Summary can label its
 * per-category groups with the same glyphs the trace rows already use.
 */
export const ACTIVITY_CATEGORY_ICON: Record<ActivityCategory, LucideIcon> = {
  search: Search,
  edit: Pencil,
  shell: Terminal,
  browser: Globe,
  read: FileText,
  memory: Brain,
  mcp: Plug,
  other: FileText,
};

/**
 * One activity-trace row: `[icon] [verb] [file icon + clickable filename]
 * [+N/−M] [badge]`, the whole row expanding to the tool's Request / Response.
 * Exported so the Execution Summary renders the exact same rows it loves in the
 * live work log instead of inventing a parallel rendering.
 */
export const ActivityItemRow = memo(function ActivityItemRow({
  item,
}: {
  item: ActivityItem;
}) {
  const [open, setOpen] = useState(false);
  const host = useHost();
  const Icon = ACTIVITY_CATEGORY_ICON[item.category];
  const hasDetail = Boolean(item.input || item.output);
  const openable = Boolean(item.filePath && host?.openFile);

  return (
    <div className="flex w-full min-w-0 flex-col">
      <button
        type="button"
        aria-expanded={open}
        disabled={!hasDetail}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'group flex w-full min-w-0 items-center gap-2 rounded-md px-3 py-2 text-left transition-colors',
          hasDetail && 'hover:bg-ds-bg-neutral-muted-default'
        )}
      >
        {/*
        Not sure if we want to duplicate the icons
        <Icon
          size={14}
          aria-hidden
          className="shrink-0 text-ds-icon-neutral-subtle-default"
        /> */}
        
        {item.running ? (
          <ShinyText
            text={item.verb}
            speed={2.5}
            className="shrink-0 !text-label-sm font-normal"
          />
        ) : (
          <span className="shrink-0 text-label-sm font-normal text-ds-text-neutral-subtle-default">
            {item.verb}
          </span>
        )}
        {openable ? (
          <span
            role="link"
            tabIndex={0}
            title={`Open ${item.filePath}`}
            onClick={(e) => {
              e.stopPropagation();
              void host?.openFile?.(item.filePath as string);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                e.stopPropagation();
                void host?.openFile?.(item.filePath as string);
              }
            }}
            className="flex min-w-0 flex-1 items-center gap-1.5 truncate text-label-sm font-medium text-ds-text-neutral-default-default hover:text-ds-text-brand-default-default hover:underline"
          >
            <FileTypeIcon path={item.filePath as string} />
            {/* Show just the file name (the full path is the click target +
                tooltip). */}
            <span className="min-w-0 truncate">
              {splitPathForDisplay(item.filePath as string).base}
            </span>
          </span>
        ) : (
          <span className="min-w-0 flex-1 truncate text-label-sm font-medium text-ds-text-neutral-default-default">
            {item.object}
          </span>
        )}
        {item.diff && (item.diff.added > 0 || item.diff.removed > 0) ? (
          // Explicit diff colors: the ds success/error TEXT tokens map to the
          // Theia foreground in the embed (not green/red), so pin them. #22c55e
          // / #ef4444 read on both light and dark.
          <span className="shrink-0 whitespace-nowrap font-mono text-label-xs tabular-nums">
            {item.diff.added > 0 ? (
              <span style={{ color: '#22c55e' }}>+{item.diff.added}</span>
            ) : null}
            {item.diff.removed > 0 ? (
              <span className="ml-1" style={{ color: '#ef4444' }}>
                −{item.diff.removed}
              </span>
            ) : null}
          </span>
        ) : null}
        {item.badge ? (
          <span className="shrink-0 rounded-full bg-ds-bg-neutral-muted-default px-1.5 py-0.5 text-label-xs text-ds-text-neutral-subtle-default">
            {item.badge}
          </span>
        ) : null}
      </button>
      <AnimatePresence initial={false}>
        {open && hasDetail ? (
          <motion.div
            key="activity-detail"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={HEIGHT_MOTION}
            className="w-full min-w-0 overflow-hidden pl-5"
          >
            <div className="mt-1 flex w-full flex-col gap-1.5">
              {item.input ? (
                <div className="w-full rounded-md bg-ds-bg-neutral-muted-default p-2 opacity-60">
                  <div className="mb-1 !text-label-xs font-medium uppercase tracking-wide text-ds-text-neutral-subtle-default">
                    Request
                  </div>
                  <MarkDown
                    content={item.input}
                    enableTypewriter={false}
                    pTextSize="text-label-xs text-ds-text-neutral-default-default"
                  />
                </div>
              ) : null}
              {item.output ? (
                <div className="w-full rounded-md bg-ds-bg-neutral-muted-default p-2 opacity-60">
                  <div className="mb-1 !text-label-xs font-medium uppercase tracking-wide text-ds-text-neutral-subtle-default">
                    Response
                  </div>
                  <MarkDown
                    content={item.output}
                    enableTypewriter={false}
                    pTextSize="text-label-xs text-ds-text-neutral-default-default"
                  />
                </div>
              ) : null}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
});
ActivityItemRow.displayName = 'ActivityItemRow';

/** Every meaningful category, minus `other` (nothing to show). */
export type MeaningCategory = Exclude<ActivityCategory, 'other'>;

/**
 * Presentation for each category, shared by the Execution Summary title pills
 * and the group headers in both the summary and the live trace: the pill noun,
 * the group name, and the count tone.
 */
export const METRIC_META: Record<
  MeaningCategory,
  { label: string; groupLabel: string; tone: string; description: string }
> = {
  search: {
    label: 'searches',
    groupLabel: 'Codebase Discovery',
    tone: 'text-ds-text-information-default-default',
    description: 'searching the codebase',
  },
  read: {
    label: 'read',
    groupLabel: 'Files Read',
    tone: 'text-ds-text-neutral-default-default',
    description: 'reading a file',
  },
  edit: {
    label: 'modified',
    groupLabel: 'Files Changed',
    tone: 'text-ds-text-status-completed-default-default',
    description: 'editing a file',
  },
  shell: {
    label: 'commands',
    groupLabel: 'Commands Run',
    tone: 'text-ds-text-neutral-default-default',
    description: 'running a command',
  },
  browser: {
    label: 'browser actions',
    groupLabel: 'Web Browsing',
    tone: 'text-ds-text-information-default-default',
    description: 'browsing the web',
  },
  memory: {
    label: 'memories',
    groupLabel: 'Project Memory',
    tone: 'text-ds-text-neutral-default-default',
    description: 'recalling project memory',
  },
  mcp: {
    label: 'connector actions',
    groupLabel: 'Connectors',
    tone: 'text-ds-text-neutral-default-default',
    description: 'calling a connector',
  },
};

/** Stable order the pills and the groups render in. */
export const METRIC_ORDER: MeaningCategory[] = [
  'search',
  'read',
  'edit',
  'shell',
  'browser',
  'memory',
  'mcp',
];

/** One category plus the operations that fired in it. */
export interface ActivityGroupView {
  category: MeaningCategory;
  items: ActivityItem[];
}

/**
 * Bucket activities by category, dropping `other` and keeping METRIC_ORDER so
 * Codebase Discovery, Files Read and Files Changed always lead.
 */
export function groupActivitiesByCategory(
  items: ActivityItem[]
): ActivityGroupView[] {
  const byCategory = new Map<MeaningCategory, ActivityItem[]>();
  for (const item of items) {
    if (item.category === 'other') continue;
    const bucket = byCategory.get(item.category);
    if (bucket) bucket.push(item);
    else byCategory.set(item.category, [item]);
  }
  return METRIC_ORDER.filter((category) => byCategory.has(category)).map(
    (category) => ({ category, items: byCategory.get(category)! })
  );
}

/**
 * One expandable group: a header (chevron, category icon, group name, count)
 * over the real trace rows for that category.
 */
function ActivityGroup({
  group,
  open,
  onToggle,
}: {
  group: ActivityGroupView;
  open: boolean;
  onToggle: () => void;
}) {
  const meta = METRIC_META[group.category];
  const Icon = ACTIVITY_CATEGORY_ICON[group.category];

  return (
    <div className="flex flex-col">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left outline-none transition-colors hover:bg-ds-bg-neutral-muted-default"
      >
        <span className="inline-flex min-w-0 items-center gap-1.5 text-sm text-ds-text-neutral-default-default">
          {open ? (
            <ChevronDown className="h-3 w-3 shrink-0" aria-hidden />
          ) : (
            <ChevronRight className="h-3 w-3 shrink-0" aria-hidden />
          )}
          <Icon
            size={13}
            aria-hidden
            className="shrink-0 text-ds-icon-neutral-subtle-default"
          />
          <span className="truncate font-medium">{meta.groupLabel}</span>
        </span>
        <span
          className={cn(
            'shrink-0 font-mono text-xs font-semibold tabular-nums',
            meta.tone
          )}
        >
          {group.items.length}
        </span>
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            key="activity-group-body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={HEIGHT_MOTION}
            className="min-w-0 overflow-hidden"
          >
            <div className="flex flex-col gap-1.5 px-1.5 pb-2 pt-0.5">
              {group.items.map((item) => (
                <ActivityItemRow key={item.id} item={item} />
              ))}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

/**
 * The grouped activity body: one expandable group per category that fired, in
 * METRIC_ORDER, inside the shared bordered surface. This is the SAME rendering
 * the Execution Summary mounts and the live `ActivityTimeline` mounts per
 * tool-run, so the summary and the live trace read identically.
 *
 * While `running`, every group starts open so progress is visible without a
 * click; once the run settles they collapse (unless the user toggled one).
 */
export const ActivityCategoryGroups = memo(function ActivityCategoryGroups({
  activities,
  running = false,
  defaultOpen = false,
  className,
}: {
  activities: ActivityItem[];
  running?: boolean;
  defaultOpen?: boolean;
  className?: string;
}) {
  const groups = useMemo(
    () => groupActivitiesByCategory(activities),
    [activities]
  );
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});

  if (!groups.length) return null;

  const defaultExpanded = defaultOpen || running;
  const isOpen = (category: MeaningCategory) =>
    overrides[category] ?? defaultExpanded;
  const toggle = (category: MeaningCategory) =>
    setOverrides((prev) => ({
      ...prev,
      [category]: !(prev[category] ?? defaultExpanded),
    }));

  return (
    <div
      className={cn(
        'divide-y divide-ds-border-neutral-subtle-default overflow-hidden rounded-md border border-ds-border-neutral-subtle-default bg-ds-bg-neutral-subtle-default',
        className
      )}
    >
      {groups.map((group) => (
        <ActivityGroup
          key={group.category}
          group={group}
          open={isOpen(group.category)}
          onToggle={() => toggle(group.category)}
        />
      ))}
    </div>
  );
});
ActivityCategoryGroups.displayName = 'ActivityCategoryGroups';

export interface ActivityTimelineProps {
  items: TimelineItem[];
  /** Whether the owning block/group is currently the live, running one. */
  running: boolean;
}

/**
 * Drop-in replacement for the flat message/tool row list inside a block. Each
 * run of tool calls renders through `ActivityCategoryGroups`, so the live trace
 * is grouped by KIND of work (Codebase Discovery / Files Read / Files Changed …)
 * exactly like the Execution Summary — it fills in dynamically instead of only
 * appearing at the end.
 */
export const ActivityTimeline = memo(function ActivityTimeline({
  items,
  running,
}: ActivityTimelineProps) {
  const entries = useMemo(() => buildActivityRenderEntries(items), [items]);

  return (
    <div className="flex flex-col gap-2.5 py-1.5">
      {entries.map((entry, index) =>
        entry.kind === 'message' ? (
          <InlineMessageRow
            key={entry.item.id}
            text={entry.item.text}
            source={entry.item.source}
            running={entry.item.running && running}
          />
        ) : (
          <ActivityCategoryGroups
            // Groups aren't individually id-stable across re-classification;
            // the run's first-item id is stable enough for this list's order.
            key={entry.group.id}
            activities={entry.group.items}
            // Only the newest run auto-opens while the block is live; older
            // runs collapse to their category headers so the trace stays short.
            running={running && index === entries.length - 1}
          />
        )
      )}
    </div>
  );
});
ActivityTimeline.displayName = 'ActivityTimeline';
