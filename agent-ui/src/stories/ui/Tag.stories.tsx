// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

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
