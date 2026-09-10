// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========

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
