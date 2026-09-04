// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { useProjectStore } from '@/store/projectStore';

interface ExportMessage {
  role?: string;
  content?: unknown;
  createdAt?: string | number;
}

/** Turn a message's content into plain text for the export. */
function contentToText(content: unknown): string {
  if (typeof content === 'string') return content;
  if (content == null) return '';
  try {
    return JSON.stringify(content, null, 2);
  } catch {
    return String(content);
  }
}

/** Derive a human title/filename from the conversation's opening prompt. */
function conversationTitle(firstUserText: string): string {
  const line = (firstUserText || '').trim().split('\n')[0].slice(0, 80);
  return line || 'Undisclosed conversation';
}

function slugify(text: string): string {
  return (
    text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 60) || 'conversation'
  );
}

/**
 * Serialize the ACTIVE conversation (all its tasks/turns, in order) to Markdown
 * and trigger a browser download. Returns false when there's nothing to export.
 */
export function exportActiveConversationToMarkdown(): boolean {
  const ps = useProjectStore.getState();
  const projectId = ps.activeProjectId;
  if (!projectId) return false;

  const stores = ps.getAllChatStores(projectId) ?? [];
  const collected: ExportMessage[] = [];
  for (const entry of stores) {
    const tasks = entry.chatStore.getState().tasks ?? {};
    for (const taskId of Object.keys(tasks)) {
      const msgs = (tasks[taskId]?.messages ?? []) as ExportMessage[];
      for (const m of msgs) collected.push(m);
    }
  }
  if (collected.length === 0) return false;

  const firstUser = collected.find((m) => m.role === 'user');
  const title = conversationTitle(contentToText(firstUser?.content));

  const lines: string[] = [`# ${title}`, ''];
  lines.push(`_Exported from Undisclosed on ${new Date().toLocaleString()}_`, '');
  for (const m of collected) {
    const text = contentToText(m.content).trim();
    if (!text) continue;
    const who = m.role === 'user' ? 'You' : 'Undisclosed';
    lines.push(`## ${who}`, '', text, '');
  }

  const markdown = lines.join('\n');
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `${slugify(title)}.md`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
  return true;
}
