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

import { Textarea } from '@/components/ui/textarea';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { useState } from 'react';
import { expect, fn, userEvent, within } from 'storybook/test';

const meta: Meta<typeof Textarea> = {
  title: 'UI/Textarea',
  component: Textarea,
  argTypes: {
    variant: { control: 'select', options: ['none', 'enhanced'] },
    size: { control: 'select', options: ['default', 'sm'] },
    state: {
      control: 'select',
      options: ['default', 'hover', 'input', 'error', 'success', 'disabled'],
    },
  },
  decorators: [
    (Story) => (
      <div className="w-[420px]">
        <Story />
      </div>
    ),
  ],
};

export default meta;

type Story = StoryObj<typeof Textarea>;

export const Default: Story = {
  args: { placeholder: 'Type a message…', rows: 4 },
};

export const WithTitle: Story = {
  args: { title: 'Description', placeholder: 'Share more detail', rows: 4 },
};

export const Required: Story = {
  args: {
    title: 'Title is required',
    required: true,
    placeholder: 'Required field',
    rows: 3,
  },
};

export const ErrorState: Story = {
  args: {
    title: 'Summary',
    state: 'error',
    note: 'Please provide at least 5 characters',
    defaultValue: 'abc',
    rows: 3,
  },
};

export const SuccessState: Story = {
  args: {
    title: 'Summary',
    state: 'success',
    note: 'Looks good',
    defaultValue: 'A real summary that is long enough.',
    rows: 3,
  },
};

export const Enhanced: Story = {
  args: {
    title: 'Enhanced',
    variant: 'enhanced',
    placeholder: 'Enhanced chrome',
    rows: 4,
  },
};

/** Multi-line typing controlled via onEnter is covered by a runtime interaction test. */
export const TypeInteraction: Story = {
  args: { placeholder: 'Type something…', onChange: fn() },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    const ta = canvas.getByPlaceholderText('Type something…');
    await expect(ta).toBeVisible();
    await userEvent.type(ta, 'Hello world');
    await expect(ta).toHaveValue('Hello world');
    await expect(args.onChange).toHaveBeenCalled();
  },
};

export const ControlledBadge: Story = {
  render: function Controlled() {
    const [value, setValue] = useState('Editable');
    return <Textarea title="Editable" value={value} onChange={(e) => setValue(e.target.value)} rows={3} />;
  },
};
