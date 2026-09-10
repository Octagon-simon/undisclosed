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

import type { Meta, StoryObj } from '@storybook/react-vite';
import { LogOut, Mail, Plus, Settings, User } from 'lucide-react';
import { useState } from 'react';
import { expect, userEvent, within } from 'storybook/test';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

const meta: Meta = {
  title: 'UI/DropdownMenu',
};

export default meta;

type Story = StoryObj;

export const Basic: Story = {
  render: () => (
    <div className="p-16">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="md">
            Open menu
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-56">
          <DropdownMenuLabel>My Account</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem>
            <User /> Profile
          </DropdownMenuItem>
          <DropdownMenuItem>
            <Settings /> Settings
          </DropdownMenuItem>
          <DropdownMenuItem disabled>
            <LogOut /> Disabled action
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  ),
};

export const DesktopActions: Story = {
  render: () => (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-ds-text-neutral-muted-default">
        Shape mirrored from TopBar folder actions (Mail = leave / share etc.)
      </p>
      <div className="p-16">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="sm">
              Actions
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-60">
            <DropdownMenuItem>
              <Mail /> Invite teammate
            </DropdownMenuItem>
            <DropdownMenuItem>
              <Plus /> New task
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Sort</DropdownMenuLabel>
            <DropdownMenuRadioGroup
              value={''}
              onValueChange={() => {
                /* noop in showcase */
              }}
            >
              <DropdownMenuRadioItem value="createdAt">
                Newest created
              </DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="updatedAt">
                Recently updated
              </DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  ),
};

export const CheckboxAndRadio: Story = {
  render: function Showcase() {
    const [showStatus, setShowStatus] = useState(true);
    const [person, setPerson] = useState('pedro');
    return (
      <div className="p-16">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="md">
              Filters
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent className="w-60">
            <DropdownMenuCheckboxItem
              checked={showStatus}
              onCheckedChange={setShowStatus}
            >
              Show status
            </DropdownMenuCheckboxItem>
            <DropdownMenuCheckboxItem checked disabled>
              Locked option
            </DropdownMenuCheckboxItem>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Assignee</DropdownMenuLabel>
            <DropdownMenuRadioGroup value={person} onValueChange={setPerson}>
              <DropdownMenuRadioItem value="pedro">Pedro</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="simon">Simon</DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    );
  },
};

export const OpenInteraction: Story = {
  render: function Wrapper() {
    return (
      <div className="p-16">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="md">
              My menu
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-56">
            <DropdownMenuItem data-testid="menu-item-profile">
              Profile
            </DropdownMenuItem>
            <DropdownMenuItem>Settings</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    const trigger = canvas.getByRole('button', { name: /my menu/i });
    await userEvent.click(trigger);
    // Content mounts in a portal → query document.body
    const item = await body.findByTestId('menu-item-profile');
    await expect(item).toBeVisible();
    // Selecting should close the popover
    await userEvent.click(item);
    await expect(body.queryByTestId('menu-item-profile')).not.toBeInTheDocument();
  },
};
