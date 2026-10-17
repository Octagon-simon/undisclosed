// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import type { Meta, StoryObj } from '@storybook/react-vite';
import { ShieldAlert } from 'lucide-react';

import { FilesChanged } from '@/components/ChatBox/MessageItem/FilesChanged';
import type { ChangedFile } from '@/lib/activityClassifier';

/**
 * The live `FilesChanged` (not the mock). The card is a title row ("Changed
 * Files" + count + `+N/-M` totals) over a SCROLLABLE list of changed files.
 * Each row is click-to-expand: it reveals that file's unified diff inline,
 * git-style, with up/down arrows to step through the hunks. Paths render
 * relative to the project root; there are no Review/Keep/Revert actions, no
 * "Active" section, no "Unified diff" toggle, and no "Show all" row.
 *
 * A file's `patch` is used directly when present (as below), else the card
 * fetches the real `git diff` from the host. Flip the toolbar sun/moon toggle
 * to check both themes.
 */
const meta: Meta<typeof FilesChanged> = {
  title: 'ChatBox/ChangedFiles',
  component: FilesChanged,
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

type Story = StoryObj<typeof FilesChanged>;

/** Build a changed file from a path + diff counts (+ optional patch text). */
const file = (
  path: string,
  added: number,
  removed: number,
  patch?: string
): ChangedFile => ({
  path,
  diff: { added, removed },
  patch,
});

const PATCH_FILES_CHANGED = `diff --git a/agent-ui/src/components/ChatBox/MessageItem/FilesChanged.tsx b/agent-ui/src/components/ChatBox/MessageItem/FilesChanged.tsx
index 1111111..2222222 100644
--- a/agent-ui/src/components/ChatBox/MessageItem/FilesChanged.tsx
+++ b/agent-ui/src/components/ChatBox/MessageItem/FilesChanged.tsx
@@ -48,6 +48,9 @@ import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
 import { SectionDivider, statusTone } from './PanelSection';
 
+const MAX_VISIBLE_HUNKS = 50;
+
 /** Count added/removed lines in a unified patch. */
 function countPatch(patch: string) {
@@ -120,7 +123,6 @@ function DiffView({ patch }: { patch: string }) {
   const [current, setCurrent] = useState(0);
-  const hunkRefs = useRef<Map<number, HTMLDivElement>>(new Map());
   return <div>{lines.length}</div>;
 }
`;

const PATCH_PANEL_SECTION = `diff --git a/agent-ui/src/components/ChatBox/MessageItem/PanelSection.tsx b/agent-ui/src/components/ChatBox/MessageItem/PanelSection.tsx
index 3333333..4444444 100644
--- a/agent-ui/src/components/ChatBox/MessageItem/PanelSection.tsx
+++ b/agent-ui/src/components/ChatBox/MessageItem/PanelSection.tsx
@@ -12,3 +12,4 @@ export function SectionDivider() {
   return <div className="border-t border-ds-border-neutral-subtle-default" />;
 }
+// end of section
`;

const ONE_FILE: ChangedFile[] = [
  file(
    'agent-ui/src/components/ChatBox/MessageItem/FilesChanged.tsx',
    24,
    6,
    PATCH_FILES_CHANGED
  ),
];

/** Modified + added + deleted files, so all three M/A/D badges are visible. */
const MANY_FILES: ChangedFile[] = [
  file(
    'agent-ui/src/components/ChatBox/MessageItem/FilesChanged.tsx',
    42,
    9,
    PATCH_FILES_CHANGED
  ),
  file(
    'agent-ui/src/components/ChatBox/MessageItem/PanelSection.tsx',
    18,
    0,
    PATCH_PANEL_SECTION
  ),
  file('agent-ui/src/lib/activityClassifier.ts', 12, 4),
  file('agent-ui/src/lib/legacyFilesChanged.ts', 0, 37),
  file('agent-ui/src/stories/panels/ChangedFiles.stories.tsx', 61, 0),
];

/** A single changed file: no secondary list, drawer row still reads correctly. */
export const OneFile: Story = {
  args: { files: ONE_FILE },
};

/** Several files: the first is featured, the rest render as the divided list. */
export const ManyFiles: Story = {
  args: { files: MANY_FILES },
};

/** The housed sensitive-config band (the mock's risk summary). */
export const WithSensitiveConfig: Story = {
  args: {
    files: MANY_FILES,
    riskSummary: (
      <span className="inline-flex items-center gap-1.5">
        <ShieldAlert
          className="h-3 w-3 text-ds-text-warning-default-default"
          aria-hidden
        />
        1 sensitive file (.env.sample) — review before keeping
      </span>
    ),
  },
};

/** No changed files -> the component renders nothing (callers can mount freely). */
export const Empty: Story = {
  args: { files: [] },
};
