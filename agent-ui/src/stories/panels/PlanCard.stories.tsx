// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import type { Meta, StoryObj } from '@storybook/react-vite';

import {
  PlanCard,
  type PlanStep,
} from '@/components/ChatBox/MessageItem/PlanCard';
import { TaskStatus } from '@/types/constants';

/**
 * The INLINE agent-progress / plan card. It is the plan surface — the decomposed
 * `taskInfo` subtasks — rendered as a normal `PanelSection` in the conversation
 * flow, the same box as the Thought Process and Execution Summary above/below it.
 * Mounted in `UserQueryGroup`; these stories render it standalone.
 *
 * This replaces the old sticky `PinnedPlanIndicator`: instead of a centered
 * "Plan · done/total" pill stuck to the top of the viewport, the plan now sits
 * with the turn and scrolls with it. While the agent works the header reads
 * "Agent working" with a pulsing cyan dot and a "Step N of M" count, and the
 * active step is an elevated row with a spinner + "running" pill; queued steps
 * are dimmed with a "queued" label.
 *
 * Flip the toolbar sun/moon toggle to check both themes.
 */
const meta: Meta<typeof PlanCard> = {
  title: 'ChatBox/PlanCard',
  component: PlanCard,
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

type Story = StoryObj<typeof PlanCard>;

/** A live turn: two steps done, one in flight, the rest queued. */
const RUNNING_STEPS: PlanStep[] = [
  {
    id: 't1',
    content: 'Find every .env template in the workspace',
    status: TaskStatus.COMPLETED,
    durationMs: 400,
  },
  {
    id: 't2',
    content: 'Read configuration dependencies across 21 files',
    status: TaskStatus.COMPLETED,
    durationMs: 1200,
  },
  {
    id: 't3',
    content: 'Scan the repo for POWER_SAVE_BLOCKER references',
    status: TaskStatus.RUNNING,
  },
  {
    id: 't4',
    content: 'Apply the patch to .env.sample and update the build config',
  },
  {
    id: 't5',
    content: 'Run the agent-ui type-check and rebuild the embed bundle',
  },
];

/** The still-running turn: "Agent working" + Step 3 of 5 + active row. */
export const Running: Story = {
  args: { steps: RUNNING_STEPS, running: true },
};

/** A finished turn: "Plan" header, full bar, every step ticked. */
export const Completed: Story = {
  args: {
    steps: RUNNING_STEPS.map((s) => ({
      ...s,
      status: TaskStatus.COMPLETED,
      durationMs: s.durationMs ?? 800,
    })),
    running: false,
  },
};

/** One step failed: red glyph + "1 failed" in the header meta. */
export const WithFailure: Story = {
  args: {
    steps: [
      RUNNING_STEPS[0],
      { ...RUNNING_STEPS[1], status: TaskStatus.FAILED },
      { ...RUNNING_STEPS[2], status: TaskStatus.COMPLETED, durationMs: 900 },
      RUNNING_STEPS[3],
    ],
    running: false,
  },
};

/** Collapsed (finished): just the header row, checklist tucked away. */
export const Collapsed: Story = {
  args: {
    steps: RUNNING_STEPS.map((s) => ({ ...s, status: TaskStatus.COMPLETED })),
    running: false,
    defaultOpen: false,
  },
};

/** A one-step plan: no plan clutter beyond a single row. */
export const SingleStep: Story = {
  args: { steps: [RUNNING_STEPS[2]], running: true },
};

/** No plan yet -> the card renders nothing (safe to mount). */
export const Empty: Story = {
  args: { steps: [] },
};
