// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import type { Meta, StoryObj } from '@storybook/react-vite';

import { SelectionPill } from '@/components/ChatBox/SelectionPill';
import { UserMessageCard } from '@/components/ChatBox/MessageItem/UserMessageCard';
import { Sparkles } from 'lucide-react';

/**
 * Design review for the selection reference the editor sends to the agent.
 * `pill` is the default; `chip` and `outline` are alternates for comparison.
 */
const meta: Meta<typeof SelectionPill> = {
  title: 'ChatBox/SelectionPill',
  component: SelectionPill,
  parameters: { layout: 'centered' },
  decorators: [
    (Story) => (
      <div className="w-[620px] bg-ds-bg-neutral-muted-default p-6">
        <Story />
      </div>
    ),
  ],
  args: {
    path: 'agent-ui/src/components/ChatBox/MessageItem/ActivityTraceCard.tsx',
    startLine: 111,
    endLine: 154,
    variant: 'pill',
    size: 'sm',
  },
  argTypes: {
    variant: { control: 'select', options: ['pill', 'chip', 'outline'] },
    size: { control: 'select', options: ['sm', 'md'] },
  },
  tags: ['autodocs'],
};

export default meta;

type Story = StoryObj<typeof SelectionPill>;

/** The reference in the user's example. */
export const Default: Story = {};

/** Three shells on the same content: pick one. */
export const Variants: Story = {
  render: () => (
    <div className="flex flex-col gap-4">
      {(['pill', 'chip', 'outline'] as const).map((variant) => (
        <div key={variant} className="flex items-center gap-3">
          <span className="w-14 text-[11px] uppercase tracking-wide text-ds-text-neutral-subtle-default">
            {variant}
          </span>
          <SelectionPill
            path="agent-ui/src/components/ChatBox/MessageItem/ActivityTraceCard.tsx"
            startLine={111}
            endLine={154}
            variant={variant}
          />
          <SelectionPill
            path="agent-ui/src/components/ChatBox/MessageItem/ActivityTraceCard.tsx"
            startLine={111}
            endLine={154}
            variant={variant}
            size="md"
          />
        </div>
      ))}
    </div>
  ),
};

/** Real file marks: React, TypeScript, Python, Markdown, JSON, YAML, image. */
export const FileTypes: Story = {
  render: () => (
    <div className="flex flex-wrap items-center gap-2">
      <SelectionPill path="agent-ui/src/components/ChatBox/MessageItem/ActivityTraceCard.tsx" startLine={111} endLine={154} />
      <SelectionPill path="packages/undisclosed-agent/src/browser/undisclosed-agent-widget.tsx" startLine={314} endLine={321} />
      <SelectionPill path="brain/app/controller/memory_controller.py" startLine={8} endLine={42} />
      <SelectionPill path="docs/agent-panel-integration-plan.md" startLine={1} endLine={20} />
      <SelectionPill path="agent-ui/package.json" startLine={1} endLine={12} />
      <SelectionPill path=".github/workflows/release.yml" startLine={30} endLine={64} />
      <SelectionPill path="site/demo-img-1.png" startLine={1} endLine={1} />
      <SelectionPill path="Dockerfile" startLine={1} endLine={9} />
    </div>
  ),
};

/** One line reads `L111`, not `L111-111`. Copying bottom-to-top still ascends. */
export const RangeFormatting: Story = {
  render: () => (
    <div className="flex flex-col gap-3">
      <SelectionPill path="src/App.tsx" startLine={111} endLine={111} />
      <SelectionPill path="src/App.tsx" startLine={154} endLine={111} />
      <span className="text-xs text-ds-text-neutral-subtle-default">
        second pill was passed endLine=111, startLine=154
      </span>
    </div>
  ),
};

/** Long names truncate; the full path + range stays in the tooltip. */
export const LongName: Story = {
  decorators: [
    (Story) => (
      <div className="w-[320px] bg-ds-bg-neutral-muted-default p-6">
        <Story />
      </div>
    ),
  ],
  args: {
    path: 'packages/undisclosed-agent/src/browser/undisclosed-agent-contribution-with-a-very-long-name.ts',
    startLine: 198,
    endLine: 206,
  },
};

/** Multiple references wrap above the input. */
export const Multiple: Story = {
  render: () => (
    <div className="flex max-w-[460px] flex-wrap items-start gap-1.5">
      <SelectionPill path="src/App.tsx" startLine={12} endLine={30} onRemove={() => {}} />
      <SelectionPill path="src/lib/router.ts" startLine={4} endLine={4} onRemove={() => {}} />
      <SelectionPill path="brain/app/main.py" startLine={90} endLine={140} onRemove={() => {}} />
    </div>
  ),
};

/** How it sits in the live composer, above the text the user is typing. */
export const InComposer: Story = {
  decorators: [
    (Story) => (
      <div className="w-[600px] bg-ds-bg-neutral-muted-default p-6">
        <Story />
      </div>
    ),
  ],
  render: () => (
    <div className="rounded-3xl border border-ds-border-information-default-default bg-ds-bg-neutral-subtle-default p-3">
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <SelectionPill
          path="agent-ui/src/components/ChatBox/MessageItem/ActivityTraceCard.tsx"
          startLine={111}
          endLine={154}
          onRemove={() => {}}
        />
      </div>
      <div className="min-h-16 px-1 text-sm text-ds-text-neutral-subtle-default">
        Refactor this into a shared section and keep the existing spacing.
      </div>
      <div className="mt-2 flex items-center justify-between">
        <div className="flex items-center gap-1 text-ds-icon-neutral-subtle-default">
          <span className="flex size-7 items-center justify-center rounded-lg hover:bg-ds-bg-neutral-strong-default">
            <Sparkles className="size-3.5" />
          </span>
        </div>
        <span className="flex size-7 items-center justify-center rounded-full bg-ds-bg-neutral-inverse-default text-ds-text-neutral-inverse-default">
          <svg viewBox="0 0 16 16" className="size-3.5" aria-hidden>
            <path
              d="M8 13V3M8 3 4 7M8 3l4 4"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
      </div>
    </div>
  ),
};

/** The floating action that appears next to a selection in the editor. */
export const PopupOverSelection: Story = {
  render: () => (
    <div className="overflow-hidden rounded-lg border border-ds-border-neutral-subtle-default bg-ds-bg-neutral-default-default">
      <div className="flex items-center justify-between border-b border-ds-border-neutral-subtle-default px-3 py-1.5">
        <span className="text-[11px] text-ds-text-neutral-subtle-default">
          ActivityTraceCard.tsx
        </span>
        <span className="font-mono text-[10px] text-ds-text-neutral-subtle-default">
          TSX
        </span>
      </div>
      <div className="relative p-3 font-mono text-[11px] leading-5">
        <div className="text-ds-text-neutral-subtle-default">110&nbsp;&nbsp;export function ActivityTraceCard() {'{'}</div>
        <div className="flex w-fit items-center gap-2 rounded-sm bg-ds-bg-information-subtle-default text-ds-text-neutral-default-default">
          <span>111&nbsp;&nbsp;&nbsp;&nbsp;const groups = useMemo(() =&gt; {'{'}</span>
          <button
            type="button"
            className="inline-flex h-6 shrink-0 items-center gap-1.5 rounded-full border border-ds-border-neutral-default-default bg-ds-bg-neutral-default-default px-2 text-[11px] font-medium text-ds-text-neutral-default-default shadow-perfect"
          >
            <Sparkles className="size-3 text-ds-icon-information-default-default" />
            Send to Agent
          </button>
        </div>
        <div className="rounded-sm bg-ds-bg-information-subtle-default text-ds-text-neutral-default-default">
          112&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;return buildActivityRenderEntries(items);
        </div>
        <div className="rounded-sm bg-ds-bg-information-subtle-default text-ds-text-neutral-default-default">
          113&nbsp;&nbsp;&nbsp;&nbsp;{'}'}, [items]);
        </div>
        <div className="text-ds-text-neutral-subtle-default">114&nbsp;&nbsp;&nbsp;&nbsp;return &lt;PanelSection …</div>
      </div>
    </div>
  ),
};

/** The sent turn: the same reference rendered as a pill in the transcript. */
export const SentTurn: Story = {
  decorators: [
    (Story) => (
      <div className="w-[620px] bg-ds-bg-neutral-muted-default p-6">
        <Story />
      </div>
    ),
  ],
  render: () => (
    <UserMessageCard
      id="sent-turn"
      content="Refactor this into a shared section and keep the existing spacing."
      selections={[
        {
          path: 'agent-ui/src/components/ChatBox/MessageItem/ActivityTraceCard.tsx',
          startLine: 111,
          endLine: 154,
        },
      ]}
      timestamp={new Date().toISOString()}
    />
  ),
};
