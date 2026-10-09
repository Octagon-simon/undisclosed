// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import type { Meta, StoryObj } from '@storybook/react-vite';

import { ThinkingBlock } from '@/components/ChatBox/MessageItem/ThinkingBlock';

/**
 * The live `ThinkingBlock` (not the mock). Phase 1 reshaped it onto the shared
 * `PanelSection` box, so it is the same card as the Execution Summary below it,
 * but a disclosure: header row (Brain + "Thought Process" + duration pill on the
 * left, step count + chevron on the right), reasoning under a hairline only when
 * open.
 *
 * Flip the toolbar sun/moon toggle to check both themes.
 */
const meta: Meta<typeof ThinkingBlock> = {
  title: 'ChatBox/ThoughtProcess',
  component: ThinkingBlock,
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

type Story = StoryObj<typeof ThinkingBlock>;

const REASONING = `Reading .env.sample to find where sibling config keys live and how the comments are phrased.
Appending UNDISCLOSED_DISABLE_POWER_SAVE_BLOCKER with an inline comment explaining the power-save behaviour it toggles.
Checking the sample set stays alphabetised so the diff stays a single appended line.`;

/** Default: open, with the duration pill and step count from the work log. */
export const Expanded: Story = {
  args: {
    reasoning: REASONING,
    duration: 'Worked for 53s',
    stepCount: 4,
    defaultOpen: true,
  },
};

/** Starting collapsed (the chevron rotates, the reasoning is hidden). */
export const Collapsed: Story = {
  args: {
    reasoning: REASONING,
    duration: 'Worked for 53s',
    stepCount: 4,
    defaultOpen: false,
  },
};

/**
 * The current live shape before duration/step-count wiring: just reasoning.
 * Header degrades to Brain + title + chevron.
 */
export const NoMeta: Story = {
  args: {
    reasoning: REASONING,
    defaultOpen: true,
  },
};

/** A single step should read "1 step completed", not "1 steps completed". */
export const SingleStep: Story = {
  args: {
    reasoning: 'Checking the parser handles a trailing comma before editing.',
    duration: 'Worked for 6s',
    stepCount: 1,
    defaultOpen: true,
  },
};
