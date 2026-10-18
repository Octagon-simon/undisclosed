// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipSimple,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { Info } from 'lucide-react';

const meta: Meta = {
  title: 'UI/Tooltip',
  parameters: {
    layout: 'centered',
  },
};

export default meta;

type Story = StoryObj;

export const Default: Story = {
  render: () => (
    <TooltipSimple content="This is an informational tooltip">
      <Button variant="ghost" size="md">
        Hover me
      </Button>
    </TooltipSimple>
  ),
};

export const Instant: Story = {
  render: () => (
    <TooltipSimple
      content="Instant label — opens with no animation"
      variant="instant"
      side="top"
    >
      <Button variant="ghost" size="md">
        Hover me
      </Button>
    </TooltipSimple>
  ),
};

export const Sides: Story = {
  decorators: [
    (StoryNode) => (
      <div className="p-20">
        <StoryNode />
      </div>
    ),
  ],
  render: () => (
    <div className="gap-20 flex flex-wrap items-start">
      <TooltipSimple content="Appears on top" side="top">
        <Button variant="ghost" size="sm">
          Top
        </Button>
      </TooltipSimple>
      <TooltipSimple content="Appears on bottom" side="bottom">
        <Button variant="ghost" size="sm">
          Bottom
        </Button>
      </TooltipSimple>
      <TooltipSimple content="Appears on the right" side="right">
        <Button variant="ghost" size="sm">
          Right
        </Button>
      </TooltipSimple>
      <TooltipSimple content="Appears on the left" side="left">
        <Button variant="ghost" size="sm">
          Left
        </Button>
      </TooltipSimple>
    </div>
  ),
};

export const Disabled: Story = {
  render: () => (
    <TooltipSimple content="Never shown" enabled={false}>
      <Button variant="outline" size="md">
        No tooltip
      </Button>
    </TooltipSimple>
  ),
};

export const RichContent: Story = {
  render: () => (
    <TooltipSimple
      content={
        <span className="flex items-center gap-2">
          <Info className="h-3.5 w-3.5" aria-hidden />
          Tooltips can hold composed React content
        </span>
      }
    >
      <Badge tone="information">Hover for hints</Badge>
    </TooltipSimple>
  ),
};

/** Manual composition from the three primitives: Tooltip + Trigger + Content. */
export const ManualComposition: Story = {
  render: () => (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="outline" size="md">
            Manual composition
          </Button>
        </TooltipTrigger>
        <TooltipContent>Built from Tooltip, TooltipTrigger and TooltipContent</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  ),
};
