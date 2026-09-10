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

import { Tag } from '@/components/ui/tag';
import type { Meta, StoryObj } from '@storybook/react-vite';

const meta: Meta<typeof Tag> = {
  title: 'UI/Tag',
  component: Tag,
  parameters: {
    layout: 'centered',
  },
  argTypes: {
    variant: {
      control: 'select',
      options: ['primary', 'secondary', 'outline', 'ghost'],
    },
    emphasis: {
      control: 'select',
      options: ['subtle', 'muted', 'default', 'strong'],
    },
    tone: {
      control: 'select',
      options: [
        'neutral',
        'success',
        'error',
        'information',
        'warning',
        'info',
        'caution',
      ],
    },
    size: {
      control: 'select',
      options: ['xxs', 'xs', 'sm', 'md', 'lg'],
    },
    text: { control: 'text', description: 'Convenience label (rendered alongside children).' },
  },
  args: {
    children: 'Tag',
    text: '',
    variant: 'secondary',
    tone: 'neutral',
    size: 'sm',
  },
};

export default meta;

type Story = StoryObj<typeof Tag>;

export const Default: Story = {
  args: { text: 'Tag label' },
};

/** chrome showcase across variants × tone matrix */
export const AllVariants: Story = {
  render: () => (
    <div className="gap-6 flex flex-col">
      <div className="gap-3 flex flex-wrap items-center">
        <Tag variant="primary" text="Primary" />
        <Tag variant="secondary" text="Secondary" />
        <Tag variant="outline" text="Outline" />
        <Tag variant="ghost" text="Ghost" />
      </div>
    </div>
  ),
};

export const Tones: Story = {
  render: () => (
    <div className="gap-3 flex flex-wrap items-center">
      <Tag tone="neutral">neutral</Tag>
      <Tag tone="success">success</Tag>
      <Tag tone="error">error</Tag>
      <Tag tone="information">information</Tag>
      <Tag tone="warning">warning</Tag>
    </div>
  ),
};

export const Sizes: Story = {
  render: () => (
    <div className="gap-4 flex items-end">
      <Tag text="xxs" size="xxs" />
      <Tag text="xs" size="xs" />
      <Tag text="sm" size="sm" />
      <Tag text="md" size="md" />
      <Tag text="lg" size="lg" />
    </div>
  ),
};
