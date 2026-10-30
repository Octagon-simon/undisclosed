// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import type { Meta, StoryObj } from "@storybook/react-vite";
import { ArrowUp, Paperclip } from "lucide-react";
import { useState, type ReactNode } from "react";

import {
  ApprovalRequestCardView,
  type ApprovalRequestCardViewProps,
  type ApprovalScope,
} from "@/components/ChatBox/MessageItem/ApprovalRequestCard";

/**
 * The governance approval prompt, shown where it actually appears: floating
 * directly above the chat composer, not inline in the transcript.
 *
 * The card carries the exact command in a scrollable mono block, the directory
 * it runs in, a policy tier chip, and a one-line description of what the
 * command does. Approve/Deny live in a footer that stays put while a long
 * command scrolls above it.
 *
 * Design-review stories. Nothing here is wired to a task; the live card is
 * store-driven and mounts at `ProjectSection` level.
 *
 * Flip the toolbar sun/moon toggle to check both themes.
 */

const noop = () => {};

function FakeTurn({ width, lines }: { width: string; lines: number }) {
  return (
    <div className={`${width} space-y-2`}>
      {Array.from({ length: lines }).map((_, index) => (
        <div
          key={index}
          className="h-2 rounded-full bg-ds-bg-neutral-subtle-default"
          style={{ width: `${55 + ((index * 17) % 40)}%` }}
        />
      ))}
    </div>
  );
}

function Scene({
  children,
  narrow = false,
}: {
  children: ReactNode;
  narrow?: boolean;
}) {
  return (
    <div
      className={`flex min-h-[620px] flex-col overflow-hidden rounded-xl border border-solid border-ds-border-neutral-default-default bg-ds-bg-neutral-muted-default ${narrow ? "w-[400px]" : "w-[600px]"}`}
    >
      <div className="min-h-[260px] flex-1 space-y-6 overflow-hidden px-4 pt-8 opacity-50">
        <div className="ml-auto w-[70%]">
          <FakeTurn width="w-full" lines={2} />
        </div>
        <FakeTurn width="w-[85%]" lines={4} />
        <div className="ml-auto w-[62%]">
          <FakeTurn width="w-full" lines={2} />
        </div>
      </div>

      <div className="border-t border-solid border-ds-border-neutral-default-default bg-ds-bg-neutral-default-default px-3 pb-3 pt-3">
        <div className="mb-2.5 flex justify-center">{children}</div>
        <div className="flex items-end gap-2 rounded-xl border border-solid border-ds-border-neutral-default-default bg-ds-bg-neutral-subtle-default px-3 py-2">
          <Paperclip
            size={15}
            aria-hidden
            className="mb-0.5 shrink-0 text-ds-text-neutral-subtle-default"
          />
          <span className="flex-1 text-label-sm text-ds-text-neutral-subtle-default">
            Reply, or describe what to change…
          </span>
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-ds-bg-brand-default-default text-ds-text-brand-inverse-default">
            <ArrowUp size={14} aria-hidden />
          </span>
        </div>
      </div>
    </div>
  );
}

const meta: Meta<typeof ApprovalRequestCardView> = {
  title: "ChatBox/ApprovalRequestCard",
  component: ApprovalRequestCardView,
  parameters: { layout: "centered" },
  decorators: [
    (Story, context: { parameters: { narrow?: boolean } }) => (
      <Scene narrow={context.parameters.narrow === true}>
        <Story />
      </Scene>
    ),
  ],
  argTypes: {
    tier: {
      control: "inline-radio",
      options: ["read_only", "workspace_write", "destructive"],
    },
  },
  args: {
    toolName: "shell_exec",
    command: "git push --force origin main",
    tier: "destructive",
    workingDirectory: "~/Documents/github/undisclosed",
    description: "Force-pushes to origin/main and rewrites its history.",
    onApprove: noop,
    onDeny: noop,
  },
  tags: ["autodocs"],
};

export default meta;

type Story = StoryObj<typeof ApprovalRequestCardView>;

/** A force-push: red tier chip, the full command, and what it will do. */
export const DestructiveShell: Story = {};

function ScopesDemo({
  initialScopes,
  ...args
}: ApprovalRequestCardViewProps & { initialScopes: ApprovalScope[] }) {
  const [scopes, setScopes] = useState<ApprovalScope[]>(initialScopes);
  return (
    <ApprovalRequestCardView
      {...args}
      selectedScopes={scopes}
      onToggleScope={(scope) =>
        setScopes((current) =>
          current.includes(scope)
            ? current.filter((item) => item !== scope)
            : [...current, scope],
        )
      }
    />
  );
}

/** A package install: amber "May change files" tier and the suppression row. */
export const WorkspaceWrite: Story = {
  render: (args: ApprovalRequestCardViewProps) => (
    <ScopesDemo {...args} initialScopes={["installs"]} />
  ),
  args: {
    tier: "workspace_write",
    command: "npm install zod",
    description: "Installs zod and updates package.json and the lockfile.",
    workingDirectory: "~/Documents/github/undisclosed/agent-ui",
  },
};

/** A file write: path and content, with File writes pre-selected. */
export const FileWrite: Story = {
  render: (args: ApprovalRequestCardViewProps) => (
    <ScopesDemo {...args} initialScopes={["writes"]} />
  ),
  args: {
    toolName: "write_to_file",
    command:
      '/Users/octagon/Documents/github/undisclosed/agent-ui/src/config.ts\n\n+ export const API_BASE = "http://localhost:8000";',
    tier: "workspace_write",
    description: "Writes a new config file with the API base URL.",
    workingDirectory: "~/Documents/github/undisclosed/agent-ui",
  },
};

/**
 * A deletion: red tier, the action named in the tag, and no suppression row.
 * Irreversible calls can never be suppressed, so offering the row would lie.
 */
export const DeleteFiles: Story = {
  args: {
    toolName: "delete_files",
    command:
      ".shots/capture-otc-headed.mjs.20261030_115756.bak\n…and 47 more",
    tier: "destructive",
    tierLabel: "Deletes files",
    description:
      "The agent will delete the 48 timestamped .bak files the user asked to clear. It deletes the named paths in your workspace, and that cannot be undone.",
  },
};

/** Forty lines of shell: the command block scrolls, the footer stays put. */
export const LongCommand: Story = {
  args: {
    command: [
      "set -euo pipefail",
      "",
      "cd ~/Documents/github/undisclosed",
      "",
      'for file in $(git ls-files "*.ts" "*.tsx"); do',
      '  if grep -q "console.log" "$file"; then',
      '    echo "stripping $file"',
      '    sed -i "" "/console\\.log/d" "$file"',
      "  fi",
      "done",
      "",
      "git add -A",
      'git commit -m "chore: remove stray console.log calls"',
      "git push origin main",
      "",
      'echo "done"',
    ].join("\n"),
    description:
      "Strips console.log from every TypeScript file, then commits and pushes the result.",
  },
};

/** Approve pressed: spinner on the button, both buttons disabled. */
export const Submitting: Story = {
  args: { submitting: "approve" },
};

/** Expired after the approval window: the card stays, Retry replaces Approve. */
export const Expired: Story = {
  args: { expired: true },
};

/** The 400px Theia right rail: the card wraps without horizontal overflow. */
export const NarrowRail: Story = {
  parameters: { narrow: true },
};

/** A read-only call that slipped through gating: quiet neutral chip. */
export const ReadOnly: Story = {
  args: {
    command: "git status --short",
    tier: "read_only",
    description: "Shows which files changed. Makes no changes.",
    workingDirectory: null,
  },
};
