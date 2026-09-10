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
import type { Meta, StoryObj } from '@storybook/react-vite';
import { Check } from 'lucide-react';

const meta: Meta<typeof Badge> = {
  title: 'UI/Badge',
  component: Badge,
  parameters: {
    layout: 'centered',
  },
  argTypes: {
    variant: {
      control: 'select',
      options: ['primary', 'secondary', 'outline', 'ghost'],
      description: 'Chrome pattern (legacy default/secondary/destructive/outline still accepted).',
    },
    emphasis: {
      control: 'select',
      options: ['subtle', 'muted', 'default', 'strong', 'inverse'],
    },
    tone: {
      control: 'select',
      options: ['neutral', 'success', 'error', 'information', 'warning'],
    },
    size: {
      control: 'select',
      options: ['xs', 'default', 'sm'],
    },
  },
  args: {
    children: 'Badge',
    variant: 'primary',
    tone: 'neutral',
    size: 'default',
  },
};

export default meta;

type Story = StoryObj<typeof Badge>;

export const Primary: Story = {
  args: { variant: 'primary', children: 'Primary' },
};
export const Secondary: Story = {
  args: { variant: 'secondary', children: 'Secondary' },
};
export const Outline: Story = {
  args: { variant: 'outline', children: 'Outline' },
};
export const Ghost: Story = {
  args: { variant: 'ghost', children: 'Ghost' },
};

/** Overriding the show-all grid is the most useful single story for visual QA. */
export const AllTones: Story = {
  render: () => (
    <div className="gap-6 flex flex-col">
      <div className="gap-3 flex flex-wrap items-center">
        <Badge variant="primary" tone="neutral">neutral</Badge>
        <Badge variant="primary" tone="success">success</Badge>
        <Badge variant="primary" tone="error">error</Badge>
        <Badge variant="primary" tone="information">information</Badge>
        <Badge variant="primary" tone="warning">warning</Badge>
      </div>
      <div className="gap-3 flex flex-wrap items-center">
        <Badge variant="secondary" tone="neutral">neutral</Badge>
        <Badge variant="outline" tone="success">success</Badge>
        <Badge variant="ghost" tone="information">information</Badge>
      </div>
    </div>
  ),
};

export const Emphases: Story = {
  render: () => (
    <div className="gap-3 flex flex-wrap items-center">
      <Badge variant="primary" emphasis="subtle">Subtle</Badge>
      <Badge variant="primary" emphasis="muted">Muted</Badge>
      <Badge variant="primary" emphasis="default">Default</Badge>
      <Badge variant="primary" emphasis="strong">Strong</Badge>
    </div>
  ),
};

export const Sizes: Story = {
  render: () => (
    <div className="gap-4 flex items-center">
      <Badge size="xs">XS</Badge>
      <Badge size="default">Default</Badge>
      <Badge size="sm">SM</Badge>
    </div>
  ),
};

export const WithContents: Story = {
  render: () => (
    <div className="gap-4 flex flex-col">
      <Badge variant="outline" tone="success">
        <Check className="h-3.5 w-3.5" /> Deployed
      </Badge>
      <Badge variant="ghost" tone="warning">
        Needs your attention
      </Badge>
    </div>
  ),
};
