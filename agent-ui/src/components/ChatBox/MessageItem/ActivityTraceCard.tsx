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
import ShinyText from '@/components/ui/ShinyText/ShinyText';
import { MarkDown } from '@/components/WorkFlow/MarkDown';
import {
  buildActivityRenderEntries,
  type ActivityCategory,
  type ActivityGroup,
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
 * Antigravity-style colored file-type badge: a small rounded square with a
 * short label in the language's brand color, so TS/PY/JSON/etc. are recognizable
 * at a glance. Special-cases well-known filenames (package.json, README, …).
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
  'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'ico', 'avif', 'bmp',
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

const CATEGORY_ICON: Record<ActivityCategory, LucideIcon> = {
  search: Search,
  edit: Pencil,
  shell: Terminal,
  browser: Globe,
  read: FileText,
  memory: Brain,
  mcp: Plug,
  other: FileText,
};

const ActivityItemRow = memo(function ActivityItemRow({
  item,
}: {
  item: ActivityItem;
}) {
  const [open, setOpen] = useState(false);
  const host = useHost();
  const Icon = CATEGORY_ICON[item.category];
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
          'group flex w-full min-w-0 items-center gap-2 rounded-md px-2.5 py-1.5 text-left transition-colors',
          hasDetail && 'hover:bg-ds-bg-neutral-muted-default'
        )}
      >
        <Icon
          size={14}
          aria-hidden
          className="shrink-0 text-ds-icon-neutral-subtle-default"
        />
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
            <span className="min-w-0 truncate">{item.object}</span>
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

const ActivityGroupRow = memo(function ActivityGroupRow({
  group,
  running,
}: {
  group: ActivityGroup;
  running: boolean;
}) {
  const [override, setOverride] = useState<boolean | null>(null);
  const open = override ?? running;

  // A single-item group reads better as one row than a group with a
  // one-line summary that just repeats it.
  if (group.items.length === 1) {
    return <ActivityItemRow item={group.items[0]} />;
  }

  return (
    <div className="flex w-full min-w-0 flex-col">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOverride((v) => !(v ?? running))}
        className="flex w-fit min-w-0 max-w-full items-center gap-1 px-2.5 py-1.5 text-left transition-opacity hover:opacity-80"
      >
        <span className="truncate text-label-sm font-normal text-ds-text-neutral-subtle-default">
          {group.summary}
        </span>
        {open ? (
          <ChevronDown
            size={14}
            aria-hidden
            className="shrink-0 text-ds-icon-neutral-subtle-default"
          />
        ) : (
          <ChevronRight
            size={14}
            aria-hidden
            className="shrink-0 text-ds-icon-neutral-subtle-default"
          />
        )}
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
            <div className="flex flex-col gap-0.5 pl-4">
              {group.items.map((item) => (
                <ActivityItemRow key={item.id} item={item} />
              ))}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
});
ActivityGroupRow.displayName = 'ActivityGroupRow';

export interface ActivityTimelineProps {
  items: TimelineItem[];
  /** Whether the owning block/group is currently the live, running one. */
  running: boolean;
}

/** Drop-in replacement for the flat message/tool row list inside a block. */
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
          <ActivityGroupRow
            // Groups aren't individually id-stable across re-classification;
            // index + first-item id is stable enough for this list's order.
            key={entry.group.id}
            group={entry.group}
            running={running && index === entries.length - 1}
          />
        )
      )}
    </div>
  );
});
ActivityTimeline.displayName = 'ActivityTimeline';
