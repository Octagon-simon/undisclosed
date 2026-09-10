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

import { Switch } from '@/components/ui/switch';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { useState } from 'react';
import { expect, fn, userEvent, within } from 'storybook/test';

const meta: Meta<typeof Switch> = {
  title: 'UI/Switch',
  component: Switch,
  parameters: { layout: 'centered' },
  argTypes: {
    size: { control: 'select', options: ['default', 'sm'] },
    variant: { control: 'select', options: ['default', 'outline'] },
    checked: { control: 'boolean' },
    disabled: { control: 'boolean' },
  },
  args: { variant: 'default' },
};

export default meta;

type Story = StoryObj<typeof Switch>;

export const Off: Story = {
  args: { checked: false },
};
export const On: Story = {
  args: { checked: true },
};
export const Small: Story = {
  args: { checked: true, size: 'sm' },
};
export const Outline: Story = {
  args: { checked: false, variant: 'outline' },
};
export const Disabled: Story = {
  args: { checked: false, disabled: true },
};

export const Row: Story = {
  decorators: [
    (StoryNode) => (
      <div className="flex min-w-[240px] justify-between px-4 py-2">
        <span className="text-sm">Notifications</span>
        <StoryNode />
      </div>
    ),
  ],
  render: function RowComp() {
    const [on, setOn] = useState(false);
    return <Switch checked={on} onCheckedChange={setOn} aria-label="Notifications" />;
  },
};

export const ClickInteraction: Story = {
  args: { onCheckedChange: fn() },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    const sw = canvas.getByRole('switch');
    await expect(sw).toBeVisible();
    await expect(sw).toHaveAttribute('data-state', 'unchecked');
    await userEvent.click(sw);
    await expect(args.onCheckedChange).toHaveBeenCalledWith(true);
    await expect(sw).toHaveAttribute('data-state', 'checked');
  },
};

export const DisabledInteraction: Story = {
  args: { disabled: true, onCheckedChange: fn() },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    const sw = canvas.getByRole('switch');
    await expect(sw).toBeDisabled();
    await expect(sw).toHaveAttribute('data-disabled', 'true');
    await expect(args.onCheckedChange).not.toHaveBeenCalled();
  },
};
