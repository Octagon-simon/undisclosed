// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import type { Meta, StoryObj } from '@storybook/react-vite';

// Side-effect import: initialise the shared i18n instance so `useTranslation`
// inside the real components resolves (Storybook's preview doesn't set it up).
import '@/i18n';

import BottomBox from '@/components/ChatBox/BottomBox';
import { Inputbox } from '@/components/ChatBox/BottomBox/InputBox';

/**
 * The live composer (plan Phase 6, spec Section 7). This renders the real
 * `Inputbox` — not the mock — so the drag/drop, attachment, picker, and
 * stop/send behaviors are the live ones.
 *
 * Phase 6 changes on display here: the opt-in "● Tools (N)" pill above the
 * textarea, the primary "Send ↑" button, and the under-composer disclaimer.
 * The left toolbar's Attach / MCPs / Skills buttons are wired here too. The
 * live `Inputbox` only renders MCPs (Hammer) and Skills (WandSparkles) when
 * their toggle callbacks are supplied, and only enables Attach (Paperclip) when
 * `onAddFile` is a function. We pass all three for every story so the icons
 * show and share one brightness — omit `onAddFile` and the paperclip renders at
 * the disabled 50% opacity, i.e. dimmer than the other two.
 *
 * Flip the toolbar sun/moon toggle to check both themes.
 */
const noop = () => {};

const meta: Meta<typeof Inputbox> = {
  title: 'ChatBox/Composer',
  component: Inputbox,
  parameters: { layout: 'centered' },
  decorators: [
    (Story) => (
      <div className="w-[600px] bg-ds-bg-neutral-muted-default p-6">
        <Story />
      </div>
    ),
  ],
  // The left toolbar is gated on these callbacks: MCPs + Skills need their
  // toggle handlers, and Attach (the paperclip) needs `onAddFile`. Supply all
  // three so every icon renders enabled and equally bright — the live app
  // passes all three. Omit `onAddFile` and the paperclip shows at 50% opacity
  // (the Button's disabled style), which reads as dimmer than MCPs/Skills.
  args: {
    onAddFile: noop,
    onToggleConnectorPanel: noop,
    onToggleSkillPanel: noop,
  },
  tags: ['autodocs'],
};

export default meta;

type Story = StoryObj<typeof Inputbox>;

const PLACEHOLDER =
  "Ask a follow-up, request modifications, or type '/' for prompt tools...";

/** Empty composer with the Tools pill: submit is disabled until you type. */
export const Idle: Story = {
  args: {
    value: '',
    onChange: noop,
    toolCount: 4,
    placeholder: PLACEHOLDER,
  },
};

/** With text: the primary "Send ↑" button is now enabled. */
export const WithText: Story = {
  args: {
    value: 'add that new env to the sample set with a comment',
    onChange: noop,
    toolCount: 4,
    placeholder: PLACEHOLDER,
  },
};

/** Task running: Stop is shown, plus Send (to queue a follow-up). */
export const Busy: Story = {
  args: {
    value: 'also trim trailing whitespace',
    onChange: noop,
    isRunning: true,
    onStop: noop,
    toolCount: 4,
    placeholder: PLACEHOLDER,
  },
};

/** Whole composer disabled. */
export const Disabled: Story = {
  args: {
    value: '',
    onChange: noop,
    disabled: true,
    toolCount: 4,
    placeholder: PLACEHOLDER,
  },
};

/** No tool count supplied: the "● Tools (N)" pill stays hidden (opt-in). */
export const NoToolCount: Story = {
  args: {
    value: '',
    onChange: noop,
    placeholder: PLACEHOLDER,
  },
};

/** The full shell (BottomBox) with no model configured: warning overlay. */
export const NoModel: Story = {
  args: { value: '', onChange: noop },
  render: () => (
    <BottomBox
      state="input"
      inputProps={{
        value: '',
        onChange: noop,
        onAddFile: noop,
        toolCount: 4,
        placeholder: PLACEHOLDER,
      }}
      noModelOverlay
      onSelectModel={noop}
    />
  ),
};

/**
 * The full shell: `BottomBox` owns the picker panels, so clicking the MCPs
 * (Hammer) or Skills (WandSparkles) buttons actually opens the connector / skill
 * list here — the closest story to the live composer behavior.
 */
export const FullShell: Story = {
  args: { value: '', onChange: noop },
  render: () => (
    <BottomBox
      state="input"
      inputProps={{
        value: '',
        onChange: noop,
        onAddFile: noop,
        toolCount: 4,
        placeholder: PLACEHOLDER,
      }}
    />
  ),
};
