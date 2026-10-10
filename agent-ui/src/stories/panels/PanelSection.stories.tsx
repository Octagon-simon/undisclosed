// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import type { Meta, StoryObj } from '@storybook/react-vite';
import { Brain, ChevronDown, Zap } from 'lucide-react';
import { useState } from 'react';

import {
  PanelSection,
  Pill,
  statusTone,
} from '@/components/ChatBox/MessageItem/PanelSection';
import { Badge } from '@/components/ui/badge';

/**
 * The shared boxed-section shell for the agent panel revamp. Thought Process,
 * Execution Summary, and the future Changed Files card all sit in this box, so
 * they read as one family. Colors are semantic `ds-*` tokens — flip the toolbar
 * sun/moon toggle to see the same box in light and dark.
 */
const meta: Meta<typeof PanelSection> = {
  title: 'ChatBox/PanelSection',
  component: PanelSection,
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

type Story = StoryObj<typeof PanelSection>;

/** Title row with an icon, a label and right-side metadata chips. */
export const Titled: Story = {
  args: {
    icon: <Zap className="h-4 w-4 text-ds-text-warning-default-default" aria-hidden />,
    title: 'Execution Summary',
    meta: (
      <>
        <span className="inline-flex items-center gap-1 rounded-md border border-ds-border-neutral-subtle-default bg-ds-bg-neutral-subtle-default px-2 py-0.5">
          <span className="font-mono font-semibold text-ds-text-information-default-default">
            8
          </span>
          searches
        </span>
        <span className="inline-flex items-center gap-1 rounded-md border border-ds-border-neutral-subtle-default bg-ds-bg-neutral-subtle-default px-2 py-0.5">
          <span className="font-mono font-semibold text-ds-text-status-completed-default-default">
            3
          </span>
          modified
        </span>
      </>
    ),
    children: (
      <p className="mt-2.5 border-t border-ds-border-neutral-subtle-default pt-2.5 text-label-xs text-ds-text-neutral-subtle-default">
        Body content renders under the title row (hairline above when you add
        one).
      </p>
    ),
  },
};

/**
 * Live section: the ring is a soft multi-colour comet that travels clockwise
 * around the box (top-left -> top-right -> bottom-right -> bottom-left) and
 * loops slowly until the turn finishes, at which point the box goes flat. The
 * band runs blue -> green -> the rest of the palette as it goes, so it changes
 * hue rather than reading as one colour. Give it some height so you can watch it
 * round each side.
 */
export const Active: Story = {
  args: {
    icon: (
      <Zap className="h-4 w-4 text-ds-text-warning-default-default" aria-hidden />
    ),
    title: 'Execution Summary',
    active: true,
    children: (
      <div className="mt-2.5 space-y-2 border-t border-ds-border-neutral-subtle-default pt-2.5 text-label-xs text-ds-text-neutral-subtle-default">
        <p>The comet starts at the top-left and runs clockwise, slowly.</p>
        <p>The band cycles blue {'->'} green {'->'} the rest of the palette.</p>
        <p>When the turn ends the ring disappears and the card is flat.</p>
      </div>
    ),
  },
};

/** No title: the box renders as a plain container for arbitrary content. */
export const NoTitle: Story = {
  args: {
    children: (
      <div className="flex items-center gap-2 text-label-xs text-ds-text-neutral-subtle-default">
        <Badge size="xs" variant="secondary" tone={statusTone('M')}>
          M
        </Badge>
        <span className="font-mono">.env.sample</span>
        <Pill>root</Pill>
      </div>
    ),
  },
};

/** With `onToggle`, the title row becomes the disclosure button (mock's Thought Process). */
function ExpandableDemo() {
  const [open, setOpen] = useState(true);
  return (
    <PanelSection
      icon={<Brain className="h-4 w-4 text-ds-text-information-default-default" aria-hidden />}
      title={
        <>
          Thought Process
          <Pill>Worked for 53s</Pill>
        </>
      }
      meta={
        <>
          4 steps completed
          <ChevronDown
            aria-hidden
            className={
              'h-3.5 w-3.5 shrink-0 text-ds-icon-neutral-subtle-default transition-transform' +
              (open ? '' : ' -rotate-90')
            }
          />
        </>
      }
      onToggle={() => setOpen((v) => !v)}
      expanded={open}
      className="w-full"
    >
      {open ? (
        <div className="mt-2.5 space-y-2 border-t border-ds-border-neutral-subtle-default pt-2.5 text-label-xs leading-relaxed text-ds-text-neutral-subtle-default">
          <p>Reading .env.sample to find where sibling config keys live…</p>
          <p>Appending the new variable with an inline comment.</p>
        </div>
      ) : null}
    </PanelSection>
  );
}

export const Expandable: Story = {
  render: () => <ExpandableDemo />,
};
