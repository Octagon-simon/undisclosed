// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import type { Meta, StoryObj } from '@storybook/react-vite';

// Side-effect import: initialise the shared i18n instance so `useTranslation`
// inside the real components resolves (Storybook's preview doesn't set it up).
import '@/i18n';

import { AgentMessageCard } from '@/components/ChatBox/MessageItem/AgentMessageCard';
import { UserMessageCard } from '@/components/ChatBox/MessageItem/UserMessageCard';

/**
 * The live user turn + agent reply (not the mock). Phase 4 of the panel revamp:
 * the user prompt is an elevated, bordered card with a `User`/timestamp header,
 * and the agent reply carries the inline cyan indicator dot.
 *
 * These render the real components, so the copy/expand affordances on the user
 * card and the feedback row on the reply are the live ones.
 *
 * Flip the toolbar sun/moon toggle to check both themes.
 */
const meta: Meta<typeof UserMessageCard> = {
  title: 'ChatBox/UserTurn',
  component: UserMessageCard,
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

type Story = StoryObj<typeof UserMessageCard>;

const PROMPT = 'add that new env to the sample set with a comment';
const REPLY =
  "Sure, I'll add that new env variable to the sample set with a descriptive comment.";

/** The user turn alone, with the header timestamp. */
export const UserTurn: Story = {
  args: {
    id: 'user-1',
    content: PROMPT,
    timestamp: '2026-10-08T22:48:31',
  },
};

/** Long enough to clamp: the copy + expand affordances show on hover. */
export const UserTurnLong: Story = {
  args: {
    id: 'user-2',
    timestamp: '2026-10-08T22:48:31',
    content: [
      'add that new env to the sample set with a comment, and while you are in',
      'there also wire the sample loader to skip blank lines and trim trailing',
      'whitespace so the generated file stays clean and diff-friendly across runs.',
      'keep the existing key ordering so reviewers can see just the one addition.',
      'a few more lines so the clamp actually kicks in and the fold gradient shows.',
    ].join('\n'),
  },
};

/** No timestamp (a message rebuilt from a source without one): header shows just "User". */
export const NoTimestamp: Story = {
  args: {
    id: 'user-3',
    content: PROMPT,
  },
};

/** The composed turn: user card, then the agent reply with the indicator dot. */
export const TurnWithReply: Story = {
  args: { id: 'user-4', content: PROMPT, timestamp: '2026-10-08T22:48:31' },
  render: (args) => (
    <div className="flex flex-col gap-3">
      <UserMessageCard {...args} />
      <AgentMessageCard id="reply-1" content={REPLY} indicator typewriter={false} />
    </div>
  ),
};

/** The agent reply dot on/off, side by side. */
export const AgentReply: Story = {
  args: { id: 'user-5', content: PROMPT },
  render: () => (
    <div className="flex flex-col gap-3">
      <AgentMessageCard id="reply-on" content={REPLY} indicator typewriter={false} />
      <AgentMessageCard id="reply-off" content={REPLY} typewriter={false} />
    </div>
  ),
};
