// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import type { Meta, StoryObj } from '@storybook/react-vite';

import { ExecutionSummary } from '@/components/ChatBox/MessageItem/ExecutionSummary';
import type { ActivityItem } from '@/lib/activityClassifier';

/**
 * The live `ExecutionSummary` (not the mock). Phase 2 of the panel revamp: the
 * shared `PanelSection` box with the turn's totals at the right end of the title
 * row, and each kind of work as its own expandable group (Codebase Discovery,
 * Files Read, Files Changed, …). Opening a group lists the real activity-trace
 * rows — `Read [icon] [filename]`, clickable filename, and the row expands to
 * the tool's Request / Response.
 *
 * Flip the toolbar sun/moon toggle to check both themes.
 */
const meta: Meta<typeof ExecutionSummary> = {
  title: 'ChatBox/ExecutionSummary',
  component: ExecutionSummary,
  parameters: { layout: 'centered' },
  decorators: [
    (Story) => (
      <div className="w-[600px] bg-ds-bg-neutral-muted-default p-6">
        <Story />
      </div>
    ),
  ],
  tags: ['autodocs'],
};

export default meta;

type Story = StoryObj<typeof ExecutionSummary>;

const SRC = 'agent-ui/src/components/ChatBox/MessageItem';

const MOCK_ACTIVITIES: ActivityItem[] = [
  {
    id: 's1',
    category: 'search',
    verb: 'Searched',
    object: 'codebase for "collectTaskActivities"',
    badge: '3 matches',
    running: false,
    input: 'query="collectTaskActivities", path="agent-ui/src"',
    output:
      'activityClassifier.ts:943 · ExecutionSummary.tsx:12 · UserQueryGroup.tsx:614',
  },
  {
    id: 's2',
    category: 'search',
    verb: 'Found files',
    object: '**/PanelSection.*',
    badge: '2 files',
    running: false,
    input: 'glob="**/PanelSection.*"',
    output: 'MessageItem/PanelSection.tsx\nstories/panels/PanelSection.stories.tsx',
  },
  {
    id: 'r1',
    category: 'read',
    verb: 'Read',
    object: `${SRC}/ExecutionSummary.tsx`,
    filePath: `${SRC}/ExecutionSummary.tsx`,
    badge: '1-224',
    running: false,
    input: `file_path="${SRC}/ExecutionSummary.tsx"`,
    output: 'export function ExecutionSummary({ activities, … }) { … }',
  },
  {
    id: 'e1',
    category: 'edit',
    verb: 'Edited',
    object: `${SRC}/ExecutionSummary.tsx`,
    filePath: `${SRC}/ExecutionSummary.tsx`,
    diff: { added: 42, removed: 9 },
    running: false,
    input: 'patch="@@ -96,6 +96,40 @@ (Execution Summary body)"',
    output: 'Applied patch to ExecutionSummary.tsx',
  },
  {
    id: 'e2',
    category: 'edit',
    verb: 'Edited',
    object: `${SRC}/ActivityTraceCard.tsx`,
    filePath: `${SRC}/ActivityTraceCard.tsx`,
    diff: { added: 6, removed: 0 },
    running: false,
    input: 'patch="@@ -219,1 +219,6 @@ (export the trace row)"',
    output: 'Applied patch to ActivityTraceCard.tsx',
  },
  {
    id: 'e3',
    category: 'edit',
    verb: 'Wrote',
    object: 'src/lib/legacyFilesChanged.ts',
    filePath: 'src/lib/legacyFilesChanged.ts',
    diff: { added: 0, removed: 37 },
    running: false,
    input: 'file_path="src/lib/legacyFilesChanged.ts", content="…"',
    output: 'Wrote 0 lines',
  },
  {
    id: 'c1',
    category: 'shell',
    verb: 'Ran',
    object: 'npm run build:agent-ui',
    badge: 'ok',
    running: false,
    input: 'command="npm run build:agent-ui"',
    output: 'asset agent-embed.umd.js 3.0 MiB [emitted]',
  },
    {
    id: 'b1',
    category: 'browser',
    verb: 'Visited',
    object: 'localhost/iframe.html',
    badge: 'ok',
    running: false,
    input: 'ej01.click()',
    output: 'DOM operation successful',
  },
];

/** The turn's stats at rest: groups collapsed. */
export const Collapsed: Story = {
  args: { activities: MOCK_ACTIVITIES },
};

/** Every group expanded: the real trace rows, filenames clickable. */
export const Expanded: Story = {
  args: { activities: MOCK_ACTIVITIES, defaultOpen: true },
};

/**
 * A still-running turn: the box starts COLLAPSED so its activity groups can't
 * fill the panel (and trap the wheel), while the title clocks "Working for Xs".
 */
export const Running: Story = {
  args: {
    activities: MOCK_ACTIVITIES,
    running: true,
    // Started ~53s ago so the live "Working for Xs" pill has something to show.
    startedAt: Date.now() - 53_000,
  },
};

/** A short turn: a single read, correct singular group. */
export const SingleGroup: Story = {
  args: { activities: [MOCK_ACTIVITIES[2]], defaultOpen: true },
};

/** No meaningful operations -> the component renders nothing (safe to mount). */
export const Empty: Story = {
  args: { activities: [] },
};
