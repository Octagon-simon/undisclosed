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
import {
  PlanCard,
  type PlanStep,
} from '@/components/ChatBox/MessageItem/PlanCard';
import { ThinkingBlock } from '@/components/ChatBox/MessageItem/ThinkingBlock';
import { UserMessageCard } from '@/components/ChatBox/MessageItem/UserMessageCard';
import type { ActivityItem, ChangedFile } from '@/lib/activityClassifier';
import { TaskStatus } from '@/types/constants';

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
  /** Earlier turns stacked above the current one (scroll-chaining story). */
  history?: ReactNode;
  prompt: string;
  timestamp?: string;
  reply: string;
  reasoning: string;
  duration?: string;
  stepCount?: number;
  activities: ActivityItem[];
  running?: boolean;
  /** Inline agent progress / plan card (Section 4b). Omit to hide the card. */
  planSteps?: PlanStep[];
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
  history,
  prompt,
  timestamp,
  reply,
  reasoning,
  duration,
  stepCount,
  activities,
  running,
  planSteps,
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
          {history}
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

          {/* Section 4b - inline agent progress / plan. Sits in the execution
              stream between Thought Process and Execution Summary, per the
              live-agent-feedback spec. It owns the glow while a plan exists. */}
          {planSteps ? (
            <PlanCard steps={planSteps} running={running} active={running} />
          ) : null}

          {/* Section 5. The comet ring lives on exactly ONE section: here only
              while there is no plan (todo list) yet, otherwise on the Plan card
              above. */}
          <ExecutionSummary
            activities={activities}
            running={running}
            active={running && !(planSteps && planSteps.length)}
            // Live "Working for Xs" pill only makes sense while running.
            startedAt={running ? Date.now() - 53_000 : undefined}
          />

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

/** The decomposition the plan card shows (Section 4b). */
const PLAN_STEPS: PlanStep[] = [
  {
    id: 'p1',
    content: 'Find every .env template in the workspace',
    status: TaskStatus.COMPLETED,
    durationMs: 400,
  },
  {
    id: 'p2',
    content: 'Read configuration dependencies across 21 files',
    status: TaskStatus.COMPLETED,
    durationMs: 1200,
  },
  {
    id: 'p3',
    content: 'Append UNDISCLOSED_DISABLE_POWER_SAVE_BLOCKER to .env.sample',
    status: TaskStatus.COMPLETED,
    durationMs: 900,
  },
  {
    id: 'p4',
    content: 'Rebuild the agent-embed bundle',
    status: TaskStatus.COMPLETED,
    durationMs: 2100,
  },
];

/** Mid-flight decomposition for the running panel ("Agent working · Step 4 of 5"). */
const RUNNING_PLAN: PlanStep[] = [
  PLAN_STEPS[0],
  PLAN_STEPS[1],
  PLAN_STEPS[2],
  {
    id: 'p4',
    content: 'Rebuild the agent-embed bundle',
    status: TaskStatus.RUNNING,
  },
  {
    id: 'p5',
    content: 'Re-run the agent-ui type-check',
  },
];

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

/**
 * A still-running turn: Execution Summary starts collapsed (thought process stays
 * expanded), and the composer shows Stop.
 */
export const Running: Story = {
  ...Conversation,
  args: {
    ...Conversation.args,
    reply: 'Working through the change - writing the file now...',
    running: true,
    planSteps: RUNNING_PLAN,
    files: [],
    riskSummary: undefined,
    composerValue: '',
    busy: true,
  },
};

/**
 * A running turn BEFORE any plan exists: no todo list yet, so the Execution
 * Summary is the section that carries the comet ring instead of the plan card.
 */
export const RunningNoPlan: Story = {
  ...Running,
  args: {
    ...Running.args,
    reply: 'Looking into the workspace before I split the work up...',
    planSteps: undefined,
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

/* ------------------------------------------------------------------------- *
 * Scroll-chaining story
 * ------------------------------------------------------------------------- */

/**
 * Three prior turns stacked ABOVE the current one. The scroll-chaining story
 * needs real content up there: the point is to reach the top of the Plan /
 * Execution boxes and confirm the wheel then scrolls the panel, revealing these
 * earlier turns. Without predecessors there is nothing above to scroll to and
 * the behaviour is invisible.
 */
const HISTORY = (
  <>
    <UserMessageCard
      id="user-0"
      content="first, scan the repo and tell me where the panel's scroll containers are defined"
      timestamp="2026-10-08T22:40:02"
    />
    <AgentMessageCard
      id="reply-0"
      content={
        'The panel body scroller is the min-h-0 flex-1 overflow-y-auto wrapper in ' +
        'ChatBox/index.tsx. The compact scroll regions live in MessageItem: PlanCard ' +
        '(max-h-64), ExecutionSummary (max-h-96), ThinkingBlock (max-h-64), plus ' +
        'LiveReasoning (max-h-40) and TaskWorkLogAccordion (max-h-[28rem]). Each is ' +
        'overflow-y-auto with its own max-height, so it scrolls internally before the ' +
        'panel does.'
      }
      indicator
      typewriter={false}
    />
    <UserMessageCard
      id="user-0b"
      content="and what happens when I scroll to the bottom of one of those little boxes?"
      timestamp="2026-10-08T22:44:19"
    />
    <AgentMessageCard
      id="reply-0b"
      content={
        'That depends on overscroll-behavior. With overscroll-contain the wheel stops ' +
        'dead at the box edge and never reaches the panel, so you get stuck. With the ' +
        'browser default (auto) the scroll chains to the nearest scrollable ancestor ' +
        'once the box hits its edge. For a nested box inside a scrollable panel, auto ' +
        'is exactly what you want.'
      }
      indicator
      typewriter={false}
    />
  </>
);

/** A long plan so the Plan card's own max-h-64 list actually scrolls. */
const LONG_PLAN: PlanStep[] = [
  'Locate the panel scroll container in ChatBox/index.tsx',
  'Inventory every inline scroll region in MessageItem',
  'Confirm each region has overflow-y-auto plus a max-h',
  'Grep the panel for overscroll-contain',
  'Remove overscroll-contain from the Plan card',
  'Remove overscroll-contain from the Execution Summary',
  'Remove overscroll-contain from the Thinking block',
  'Remove overscroll-contain from LiveReasoning',
  'Remove overscroll-contain from the work-log accordion',
  'Leave input-select untouched (a dropdown must contain)',
  'Wire the Storybook scroll-chaining story',
  'Run the agent-ui type-check',
  'Rebuild the agent-embed bundle',
  'Eyeball the change in the running app',
].map((content, i) => ({
  id: `sp${i}`,
  content,
  status: TaskStatus.COMPLETED,
  durationMs: 400 + i * 130,
}));

/** A long activity log so the Execution Summary's max-h-96 group scrolls. */
const LONG_ACTIVITIES: ActivityItem[] = [
  ...ACTIVITIES,
  readItem('agent-ui/src/components/ChatBox/index.tsx', 'r2', '1-1720'),
  editItem(
    'agent-ui/src/components/ChatBox/MessageItem/PlanCard.tsx',
    3,
    3,
    'e4'
  ),
  editItem(
    'agent-ui/src/components/ChatBox/MessageItem/ThinkingBlock.tsx',
    2,
    2,
    'e5'
  ),
  editItem('agent-ui/src/components/ChatBox/LiveReasoning.tsx', 2, 2, 'e6'),
  editItem(
    'agent-ui/src/components/ChatBox/MessageItem/TaskWorkLogAccordion.tsx',
    4,
    4,
    'e7'
  ),
  readItem('agent-ui/src/components/ui/input-select.tsx', 'r3', '360-372'),
];

/** Long reasoning so the Thought Process body's max-h-64 box scrolls too. */
const LONG_REASONING = [
  'The panel body is the only unconstrained scroller, so it is the correct place for the wheel to land once a nested box hits its edge.',
  'Each inline box keeps its own overflow-y-auto and max-h so short content stays compact; only the chaining behaviour changes.',
  'overscroll-behavior: contain is the single property that blocks chaining, so removing it restores the browser default, auto.',
  'input-select is a dropdown and must keep contain; that is the one deliberate exception in the panel.',
  'Chaining is a spec default, so no JavaScript wheel handler is needed: the browser walks up to the nearest scrollable ancestor for us.',
  'If the whole page ever starts scrolling when the panel hits its end, the fix is overscroll-contain on the PANEL root, not on these inner boxes.',
].join('\n');

/**
 * Proof of the nested-scroll fix.
 *
 * The Plan card, Execution Summary and Thought Process are each `overflow-y-auto`
 * with a `max-h`, and NONE of them sets `overscroll-contain` any more.
 *
 * Test it like this (the whole point of the story):
 *   1. Hover the Plan card and scroll. You scroll INSIDE the card first.
 *   2. Keep scrolling in the SAME direction once the card hits its edge. The
 *      wheel now chains to the panel body and the earlier turns above scroll
 *      into view. Before the fix, `overscroll-contain` ate that wheel and you
 *      were stuck in the box.
 *   3. Repeat over the Execution Summary and the Thought Process box.
 *
 * Both inner regions are padded past their max-h, and three prior turns are
 * stacked above, so there is always something to reach.
 */
export const ScrollChaining: Story = {
  args: {
    ...Conversation.args,
    history: HISTORY,
    reply:
      'Done. The inner boxes no longer trap the wheel: once a box hits its edge, ' +
      'the panel takes over and the earlier turns scroll into view.',
    reasoning: LONG_REASONING,
    activities: LONG_ACTIVITIES,
    planSteps: LONG_PLAN,
  },
};
