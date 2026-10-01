// Copyright (c) 2026 Simon Ugorji

/**
 * Conversation HANDOFF: a structured carry-forward document for branching a
 * long conversation into a NEW chat without re-sending the whole transcript
 * (and paying its token cost again).
 *
 * The layout follows what a real agent handoff needs to be useful to the next
 * session (the "session handoff" pattern): objective, status, source of truth,
 * files changed, commands run and their results, what was verified vs not,
 * blockers, and the next safe action. It is NOT a transcript.
 *
 * The brain is the primary source (`/memory/handoff`), which returns both a
 * structured `sections` breakdown and a rendered Markdown view derived from the
 * cumulative rolling summary (objective, status, files, commands, verification,
 * blockers, next action). When the brain has no summary yet (a brand-new
 * conversation), we fall back to a deterministic build from the live messages.
 *
 * This lives next to `exportChat` on purpose: "Export chat" hands the user the
 * FULL transcript; "Export handoff" hands them the TOKEN-CHEAP brief.
 */

import type { HandoffSections, HandoffTimelineTurn } from '@/api/brain';
import { getAuthStore } from '@/store/authStore';
import { useProjectStore } from '@/store/projectStore';

interface HandoffMessage {
  role?: string;
  content?: unknown;
  createdAt?: string | number;
}

/** Turn a message's content into plain text. */
function contentToText(content: unknown): string {
  if (typeof content === 'string') return content;
  if (content == null) return '';
  try {
    return JSON.stringify(content, null, 2);
  } catch {
    return String(content);
  }
}

/** Derive a human title from the conversation's opening prompt. */
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
      .slice(0, 60) || 'handoff'
  );
}

/** Collapse whitespace and cap length. */
function oneLine(text: string, max: number): string {
  return text.replace(/\s+/g, ' ').trim().slice(0, max);
}

/** Collect the active conversation's messages (all tasks, in order). */
function collectMessages(projectId: string): HandoffMessage[] {
  const stores = useProjectStore.getState().getAllChatStores(projectId) ?? [];
  const collected: HandoffMessage[] = [];
  for (const entry of stores) {
    const tasks = entry.chatStore.getState().tasks ?? {};
    for (const taskId of Object.keys(tasks)) {
      const msgs = (tasks[taskId]?.messages ?? []) as HandoffMessage[];
      for (const m of msgs) collected.push(m);
    }
  }
  return collected;
}

/**
 * Deterministic fallback sections built from the live messages, used only when
 * the brain has no rolling summary to render (e.g. the first turn). It pairs
 * each user ask with the next assistant reply so the handoff still reads like a
 * brief rather than a dump.
 */
function localSections(messages: HandoffMessage[]): HandoffSections {
  const timeline: HandoffTimelineTurn[] = [];
  let n = 0;
  for (let i = 0; i < messages.length; i += 1) {
    const msg = messages[i];
    if (msg.role !== 'user') continue;
    const user = oneLine(contentToText(msg.content), 200);
    if (!user) continue;
    n += 1;
    let did = '';
    for (let j = i + 1; j < messages.length; j += 1) {
      if (messages[j].role === 'assistant') {
        did = oneLine(contentToText(messages[j].content), 300);
        break;
      }
      if (messages[j].role === 'user') break;
    }
    timeline.push({
      n,
      status: 'done',
      user,
      did,
      files: [],
      commands: [],
      verified: [],
      next: '',
    });
  }

  const first = timeline[0];
  const last = timeline[timeline.length - 1];
  return {
    objective: first?.user ?? '',
    status: last ? 'done' : '',
    status_line: last ? `Turn ${last.n}: ${last.did}` : '',
    turn_count: timeline.length,
    updated_at: '',
    rolling: '',
    files: [],
    commands: [],
    verified: [],
    blockers: [],
    next_action: '',
    timeline,
  };
}

/** Fetch the brain's structured + rendered handoff for the active project. */
async function fetchBrainHandoff(
  projectId: string,
  spaceId?: string | null
): Promise<{ markdown: string; sections: HandoffSections | null }> {
  try {
    const { memoryHandoff } = await import('@/api/brain');
    const auth = getAuthStore() as unknown as {
      email?: string | null;
      user_id?: number | string | null;
    };
    const res = await memoryHandoff({
      projectId,
      spaceId: spaceId ?? null,
      email: auth?.email ?? null,
      userId: auth?.user_id ?? null,
    });
    if (!res.found) return { markdown: '', sections: null };
    return { markdown: res.markdown.trim(), sections: res.sections };
  } catch {
    // Handoff must never throw into a toolbar click; fall back to local build.
    return { markdown: '', sections: null };
  }
}

/** Push a `## Heading` + bullet list, skipping the whole block when empty. */
function pushList(
  lines: string[],
  heading: string,
  items: string[],
  emptyLine?: string
): void {
  const bullets = items.filter((item) => item && item.trim());
  if (!bullets.length && !emptyLine) return;
  lines.push(`## ${heading}`, '');
  if (bullets.length) {
    for (const item of bullets) lines.push(`- ${item}`);
  } else if (emptyLine) {
    lines.push(emptyLine);
  }
  lines.push('');
}

/** Push a `## Heading` + paragraph, skipping when empty. */
function pushText(lines: string[], heading: string, text: string): void {
  const body = (text || '').trim();
  if (!body) return;
  lines.push(`## ${heading}`, '', body, '');
}

/**
 * Build the handoff Markdown for the ACTIVE conversation. Returns null when
 * there is no active project or nothing to summarize.
 */
export async function buildHandoffMarkdown(): Promise<string | null> {
  const ps = useProjectStore.getState();
  const projectId = ps.activeProjectId;
  if (!projectId) return null;

  const project = ps.getProjectById(projectId);
  const messages = collectMessages(projectId);
  const firstUser = messages.find((m) => m.role === 'user');
  const title = conversationTitle(contentToText(firstUser?.content));

  const brain = await fetchBrainHandoff(projectId, project?.spaceId);
  const sections = brain.sections ?? localSections(messages);
  const hasAnything =
    sections.turn_count > 0 ||
    Boolean(sections.objective) ||
    Boolean(brain.markdown);
  if (!hasAnything) return null;

  const generatedAt = new Date().toLocaleString();
  const lines: string[] = [];

  lines.push(`# Handoff: ${title}`, '');
  lines.push(
    '> Carry-forward context generated from an Undisclosed conversation on ' +
      `${generatedAt}. Paste this at the START of a new chat. Treat it as the ` +
      'established state of this work and continue from here; you do NOT have ' +
      'the full transcript.',
    ''
  );

  lines.push('## Overview', '');
  if (project?.name) lines.push(`- **Project:** ${project.name}`);
  lines.push(`- **Generated:** ${generatedAt}`);
  lines.push(`- **Turns summarized:** ${sections.turn_count}`);
  if (sections.updated_at)
    lines.push(`- **Last updated:** ${sections.updated_at}`);
  lines.push(
    `- **Status:** ${sections.status_line || sections.status || 'in progress'}`
  );
  lines.push('');

  pushText(lines, 'Objective', sections.objective);

  const sourceOfTruth = sections.files.length
    ? ['Trust the files and paths below over the summary prose:', ...sections.files]
    : [];
  pushList(
    lines,
    'Source of truth',
    sourceOfTruth,
    'No files were recorded; treat the turn-by-turn summary below as the record.'
  );

  pushList(lines, 'Files and routes changed', sections.files);
  pushList(lines, 'Commands run and results', sections.commands);

  lines.push('## Verification', '');
  if (sections.verified.length) {
    lines.push('**Verified**', '');
    for (const v of sections.verified) lines.push(`- ${v}`);
  } else {
    lines.push('**Verified**', '', '- Nothing was explicitly recorded.');
  }
  lines.push('');
  lines.push('**Not verified**', '');
  lines.push(
    '- Anything not listed under Verified above (tests, builds, rendered UI, ' +
      'deploys). Re-check before building on this work.'
  );
  lines.push('');

  pushList(lines, 'Blockers', sections.blockers, 'None recorded.');

  pushText(
    lines,
    'Next safe action',
    sections.next_action || 'Continue from the last request below.'
  );

  if (sections.timeline.length) {
    lines.push('## What happened (turn by turn)', '');
    for (const turn of sections.timeline) {
      const icon =
        turn.status === 'done' ? '✅' : turn.status === 'failed' ? '❌' : '⏸️';
      lines.push(`**Turn ${turn.n}** ${icon}`);
      lines.push(`- **User:** ${turn.user}`);
      if (turn.did) lines.push(`- **Did:** ${turn.did}`);
      if (turn.files.length) {
        for (const f of turn.files) lines.push(`  - \`${f}\``);
      }
      if (turn.verified.length)
        lines.push(`- **Verified:** ${turn.verified.join('; ')}`);
      if (turn.next) lines.push(`- **Next:** ${turn.next}`);
      lines.push('');
    }
  }

  pushText(lines, 'Earlier context (folded turns)', sections.rolling);

  // Fall back to the brain's rendered markdown only when it adds detail the
  // structured sections could not carry.
  if (!sections.timeline.length && brain.markdown) {
    pushText(lines, 'Conversation so far', brain.markdown);
  }

  const lastUser = [...messages].reverse().find((m) => m.role === 'user');
  pushText(lines, 'Last request', contentToText(lastUser?.content).trim());

  return lines.join('\n');
}

/**
 * Build the handoff and trigger a Markdown download. Returns false when there
 * is nothing to export.
 */
export async function exportActiveConversationHandoff(): Promise<boolean> {
  const markdown = await buildHandoffMarkdown();
  if (!markdown) return false;

  const title = markdown.match(/^# Handoff:\s*(.+)$/m)?.[1] ?? 'handoff';
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `handoff-${slugify(title)}.md`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
  return true;
}
