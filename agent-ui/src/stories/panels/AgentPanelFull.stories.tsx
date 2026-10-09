// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import type { Meta, StoryObj } from '@storybook/react-vite';
import { ShieldAlert } from 'lucide-react';
import type { ReactNode } from 'react';

// Side-effect import: the real turn cards + composer use `useTranslation`;
// Storybook's preview doesn't initialise i18n on its own.
import '@/i18n';

import { TelemetryStripView } from '@/agent-embed/TelemetryStrip';
import BottomBox from '@/components/ChatBox/BottomBox';
import { AgentMessageCard } from '@/components/ChatBox/MessageItem/AgentMessageCard';
import { ExecutionSummary } from '@/components/ChatBox/MessageItem/ExecutionSummary';
import { FilesChanged } from '@/components/ChatBox/MessageItem/FilesChanged';
import { ThinkingBlock } from '@/components/ChatBox/MessageItem/ThinkingBlock';
import { UserMessageCard } from '@/components/ChatBox/MessageItem/UserMessageCard';
import type { ActivityItem, ChangedFile } from '@/lib/activityClassifier';

/**
 * Phase 8 assembly (plan section "Phase 8: Assembly, theming, QA, cleanup"): the
 * WHOLE revamped panel in one frame, built out of the REAL components, not the mock.
 *
 * Every section is the live component the running app mounts:
 *   Section 1  top header          -> the host's NATIVE Theia title bar; it is
 *                                     NOT part of agent-ui, so it is
 *                                     intentionally absent here (verified in
 *                                     Phase 7, see the integration plan).
 *   Section 2  telemetry sub-strip -> `TelemetryStripView`
 *   Section 3  user turn + reply   -> `UserMessageCard` + `AgentMessageCard`
 *   Section 4  thought process     -> `ThinkingBlock`
 *   Section 5  execution summary   -> `ExecutionSummary`
 *   Section 6  changed files       -> `FilesChanged`
 *   Section 7  composer            -> `BottomBox` (owns the picker panels)
 *
 * Layout follows the LIVE order in `UserQueryGroup` (the END block stacks the
 * work summaries ABOVE the reply: Thinking -> Execution -> reply -> files), not
 * the mock's older reply-first order. The chat column matches
 * `ProjectChatContainer`'s `max-w-[600px]` so the wrap is the real one.
 *
 * Two honest gaps vs. the mock, both commented at their mount site below:
 *   - `ThinkingBlock` passes `duration`/`stepCount` here for the designed look,
 *     but `UserQueryGroup` does not wire them yet, so the running app shows no
 *     duration pill / step count on this surface.
 *   - the "Tools (N)" pill needs a live tool-count source; none exists yet.
 *
 * Flip the toolbar sun/moon toggle for light/dark, and use `NarrowRail` for the
 * ~400px Theia right-rail width.
 */

const noop = () => {};

const PLACEHOLDER =
  "Ask a follow-up, request modifications, or type '/' for prompt tools...";

/** Everything the assembled panel needs; mirrors what the live turn carries. */
export interface PanelFullProps {
  /** Telemetry (Section 2). */
  brainState?: 'live' | 'dead' | 'checking';
  usedTokens?: number;
  windowTokens?: number;

  /** Turn (Sections 3-6). */
  prompt: string;
  timestamp?: string;
  reply: string;
  reasoning: string;
  duration?: string;
  stepCount?: number;
  activities: ActivityItem[];
  running?: boolean;
  files: ChangedFile[];
  riskSummary?: ReactNode;

  /** Composer (Section 7). */
  composerValue: string;
  toolCount?: number;
  busy?: boolean;
}

/** The assembled panel: real components in the host's flex column. */
function PanelFull({
  brainState = 'live',
  usedTokens = 4_420_000,
  windowTokens = 8_000_000,
  prompt,
  timestamp,
  reply,
  reasoning,
  duration,
  stepCount,
  activities,
  running,
  files,
  riskSummary,
  composerValue,
  toolCount,
  busy,
}: PanelFullProps) {
  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-ds-bg-neutral-subtle-default text-ds-text-neutral-default-default">
      {/* Section 2 - telemetry sub-strip (panel-level, directly under the
          host's native title bar). */}
      <TelemetryStripView
        brainState={brainState}
        usedTokens={usedTokens}
        windowTokens={windowTokens}
        onRestart={noop}
      />

      {/* Scrollable conversation body, matching ProjectChatContainer's width. */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-[600px] flex-col gap-2 px-6 py-3">
          {/* Section 3 (user) */}
          <UserMessageCard id="user-1" content={prompt} timestamp={timestamp} />

          {/* Section 4 - duration/stepCount are passed here so the designed
              header is reviewable. UserQueryGroup now wires the elapsed pill
              (`durationMs`, from the task timer); stepCount is not wired yet. */}
          <ThinkingBlock
            reasoning={reasoning}
            duration={duration}
            stepCount={stepCount}
            defaultOpen
          />

          {/* Section 5 */}
          <ExecutionSummary activities={activities} running={running} />

          {/* Section 3 (reply) - after the work summaries, per the live order. */}
          <AgentMessageCard
            id="reply-1"
            content={reply}
            indicator
            typewriter={false}
          />

          {/* Section 6 */}
          <FilesChanged files={files} riskSummary={riskSummary} onOpen={noop} />
        </div>
      </div>

      {/* Section 7 - composer shell (owns the MCPs/Skills picker panels). The
          Tools pill is opt-in; it only shows when a toolCount is supplied. */}
      <div className="shrink-0 px-4 pb-3 pt-1">
        <div className="mx-auto w-full max-w-[600px]">
          <BottomBox
            state="input"
            inputProps={{
              value: composerValue,
              onChange: noop,
              onAddFile: noop,
              onToggleConnectorPanel: noop,
              onToggleSkillPanel: noop,
              toolCount,
              isRunning: busy,
              onStop: noop,
              placeholder: PLACEHOLDER,
            }}
          />
        </div>
      </div>
    </div>
  );
}

const meta: Meta<typeof PanelFull> = {
  title: 'ChatBox/AgentPanelFull',
  component: PanelFull,
  parameters: { layout: 'fullscreen' },
  tags: ['autodocs'],
  decorators: [
    (Story) => (
      <div className="flex h-screen w-full justify-center bg-ds-bg-neutral-muted-default p-4">
        <div className="h-full w-full max-w-[920px] overflow-hidden rounded-xl border border-ds-border-neutral-default-default shadow-lg">
          <Story />
        </div>
      </div>
    ),
  ],
};

export default meta;

type Story = StoryObj<typeof PanelFull>;

/* Shared sample data, matching the panel-revamp spec's scenario. */
const file = (path: string, added: number, removed: number): ChangedFile => ({
  path,
  diff: { added, removed },
});

const readItem = (
  path: string,
  id: string,
  badge?: string
): ActivityItem => ({
  id,
  category: 'read',
  verb: 'Read',
  object: path,
  filePath: path,
  badge,
  running: false,
  input: `file_path="${path}"`,
  output: `// ${path} contents`,
});

const editItem = (
  path: string,
  added: number,
  removed: number,
  id: string
): ActivityItem => ({
  id,
  category: 'edit',
  verb: 'Edited',
  object: path,
  filePath: path,
  diff: { added, removed },
  running: false,
  input: `patch="@@ ${path} @@"`,
  output: `Applied patch to ${path}`,
});

/** The spec's scenario: 8 searches, 1 read, 3 modified — as real activity. */
const SEARCH_TERMS = [
  'collectTaskActivities',
  'ExecutionSummary',
  'ActivityItemRow',
  'changed files',
  'keep all',
  'revert all',
  'review all',
  'panel-revamp',
];

const ACTIVITIES: ActivityItem[] = [
  ...SEARCH_TERMS.map((term, i) => ({
    id: `s${i}`,
    category: 'search' as const,
    verb: 'Searched',
    object: `codebase for "${term}"`,
    badge: `${i + 1} matches`,
    running: false,
    input: `query="${term}", path="agent-ui/src"`,
    output: `${i + 1} matches for "${term}"`,
  })),
  readItem(
    'agent-ui/src/components/ChatBox/MessageItem/ExecutionSummary.tsx',
    'r1',
    '1-224'
  ),
  editItem(
    'agent-ui/src/components/ChatBox/MessageItem/ExecutionSummary.tsx',
    42,
    9,
    'e1'
  ),
  editItem(
    'agent-ui/src/components/ChatBox/MessageItem/PanelSection.tsx',
    18,
    0,
    'e2'
  ),
  editItem('agent-ui/src/lib/activityClassifier.ts', 12, 4, 'e3'),
];

const FILES: ChangedFile[] = [
  file('agent-ui/src/components/ChatBox/MessageItem/FilesChanged.tsx', 42, 9),
  file('agent-ui/src/components/ChatBox/MessageItem/PanelSection.tsx', 18, 0),
  file('agent-ui/src/lib/activityClassifier.ts', 12, 4),
  file('agent-ui/src/lib/legacyFilesChanged.ts', 0, 37),
];

const REASONING = `Reading .env.sample to find where sibling config keys live and how the comments are phrased.
Appending UNDISCLOSED_DISABLE_POWER_SAVE_BLOCKER with an inline comment explaining the power-save behaviour it toggles.
Checking the sample set stays alphabetised so the diff stays a single appended line.`;

/** The full panel: live turn, work summaries, changed files, composer. */
export const Conversation: Story = {
  args: {
    prompt: 'add that new env to the sample set with a comment',
    timestamp: '2026-10-08T22:48:31',
    reply:
      "Sure, I'll add that new env variable to the sample set with a descriptive comment.",
    reasoning: REASONING,
    duration: 'Worked for 53s',
    stepCount: 4,
    activities: ACTIVITIES,
    files: FILES,
    riskSummary: (
      <span className="inline-flex items-center gap-1.5">
        <ShieldAlert
          className="h-3 w-3 text-ds-text-warning-default-default"
          aria-hidden
        />
        1 sensitive file (.env.sample) - review before keeping
      </span>
    ),
    composerValue: '',
    toolCount: 4,
  },
};

/** The same panel at the Theia right-rail width (~400px), to catch wrap/overflow. */
export const NarrowRail: Story = {
  ...Conversation,
  decorators: [
    (Story) => (
      <div className="flex h-screen w-full bg-ds-bg-neutral-muted-default">
        <div className="ml-auto h-full w-[400px] overflow-hidden border-l border-ds-border-neutral-default-default">
          <Story />
        </div>
      </div>
    ),
  ],
};

/** A still-running turn: Execution Summary groups start open, composer shows Stop. */
export const Running: Story = {
  ...Conversation,
  args: {
    ...Conversation.args,
    reply: 'Working through the change - writing the file now...',
    running: true,
    files: [],
    riskSummary: undefined,
    composerValue: '',
    busy: true,
  },
};

/** A short turn that changed nothing yet: the Changed Files card is absent. */
export const NoChanges: Story = {
  ...Conversation,
  args: {
    ...Conversation.args,
    reply: 'Looking at how `.env.sample` is structured first...',
    reasoning:
      'Checking the parser handles a trailing comma before editing anything.',
    duration: 'Worked for 6s',
    stepCount: 1,
    activities: ACTIVITIES.slice(0, 2),
    files: [],
    riskSummary: undefined,
    composerValue: '',
  },
};

/** Brain down: the telemetry strip flips to the offline tone + Restart. */
export const BrainOffline: Story = {
  ...Conversation,
  args: {
    ...Conversation.args,
    brainState: 'dead',
    usedTokens: 0,
    windowTokens: 1_000_000,
  },
};
