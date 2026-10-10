// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import type { Meta, StoryObj } from '@storybook/react-vite';

import {
  TelemetryStripView,
  type TelemetryStripViewProps,
} from '@/agent-embed/TelemetryStrip';

/**
 * The panel telemetry sub-strip (plan Phase 5, spec Section 2): the quiet
 * status row directly below the host's native title bar — brain liveness +
 * session on the left, the context-window gauge pill on the right.
 *
 * This renders the live presentational component (`TelemetryStripView`), not
 * the mock. The container `TelemetryStrip` adds the brain poller + context
 * gauge; the story drives the same props directly so every state is reviewable
 * without a running backend.
 *
 * Flip the toolbar sun/moon toggle to check both themes.
 */
const meta: Meta<typeof TelemetryStripView> = {
  title: 'ChatBox/TelemetryStrip',
  component: TelemetryStripView,
  parameters: { layout: 'centered' },
  decorators: [
    (Story) => (
      <div className="w-[720px] bg-ds-bg-neutral-subtle-default">
        <Story />
      </div>
    ),
  ],
  tags: ['autodocs'],
};

export default meta;

type Story = StoryObj<typeof TelemetryStripView>;

const noop = () => {};

const base: TelemetryStripViewProps = {
  brainState: 'live',
  usedTokens: 4_420_000,
  windowTokens: 8_000_000,
  onRestart: noop,
};

/** The mock's data: brain live, `4.42M / 8M (55%)`. */
export const Live: Story = {
  args: { ...base },
};

/** Brain down: red dot, "Brain offline", and the Restart affordance. */
export const Offline: Story = {
  args: { ...base, brainState: 'dead', usedTokens: 0, windowTokens: 1_000_000 },
};

/** Cold start: amber pulsing dot while the health probe is in flight. */
export const Checking: Story = {
  args: { ...base, brainState: 'checking' },
};

/** A near-full window — 85% (the pill itself stays neutral; the level only
 *  drives the in-chat context notice). */
export const HighUsage: Story = {
  args: { ...base, usedTokens: 6_800_000, windowTokens: 8_000_000 },
};

/** No conversation yet: the gauge reads `0 / 1M (0%)`, never a bare 0. */
export const Empty: Story = {
  args: { ...base, usedTokens: 0, windowTokens: 1_000_000 },
};
