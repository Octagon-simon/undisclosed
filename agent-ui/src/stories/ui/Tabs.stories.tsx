// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

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
