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

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { Meta, StoryObj } from '@storybook/react-vite';

const meta: Meta = {
  title: 'UI/Tabs',
};

export default meta;

type Story = StoryObj;

function TabShell({ appearance }: { appearance?: 'default' | 'outline' | 'border' | 'ghost' }) {
  return (
    <Tabs defaultValue="code" orientation="horizontal">
      <TabsList appearance={appearance}>
        <TabsTrigger value="code">Code</TabsTrigger>
        <TabsTrigger value="terminal">Terminal</TabsTrigger>
        <TabsTrigger value="browser">Browser</TabsTrigger>
      </TabsList>
      <TabsContent value="code">
        <div className="mt-4 rounded-lg border border-ds-border-neutral-subtle-default p-6 text-sm text-ds-text-neutral-default-default">
          Code pane — mirrors the Session preview tab row.
        </div>
      </TabsContent>
      <TabsContent value="terminal">
        <div className="mt-4 rounded-lg border border-ds-border-neutral-subtle-default p-6 text-sm text-ds-text-neutral-default-default">
          Terminal pane.
        </div>
      </TabsContent>
      <TabsContent value="browser">
        <div className="mt-4 rounded-lg border border-ds-border-neutral-subtle-default p-6 text-sm text-ds-text-neutral-default-default">
          Browser pane.
        </div>
      </TabsContent>
    </Tabs>
  );
}

export const Default: Story = {
  render: () => (
    <div className="p-6">
      <TabShell appearance="default" />
    </div>
  ),
};

export const Outline: Story = {
  render: () => (
    <div className="p-6">
      <TabShell appearance="outline" />
    </div>
  ),
};

export const Border: Story = {
  render: () => (
    <div className="p-6">
      <TabShell appearance="border" />
    </div>
  ),
};

export const Ghost: Story = {
  render: () => (
    <div className="p-6">
      <TabShell appearance="ghost" />
    </div>
  ),
};

export const Vertical: Story = {
  render: () => (
    <div className="p-6">
      <Tabs defaultValue="one" orientation="vertical">
        <TabsList>
          <TabsTrigger value="one">One</TabsTrigger>
          <TabsTrigger value="two">Two</TabsTrigger>
        </TabsList>
        <TabsContent value="one" className="mt-4 text-sm text-ds-text-neutral-default-default">
          Tabs also work vertically via orientation. First panel.
        </TabsContent>
        <TabsContent value="two" className="mt-4 text-sm text-ds-text-neutral-default-default">
          Second panel.
        </TabsContent>
      </Tabs>
    </div>
  ),
};
