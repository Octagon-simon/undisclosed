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

/**
 * Pure classification/aggregation layer for the compact "Worked for Xs /
 * Explored…" activity trace UI. Consumes the `ToolItem`/`MessageItem`
 * timeline `TaskWorkLogAccordion` already builds from paired
 * ACTIVATE_TOOLKIT/DEACTIVATE_TOOLKIT events — no new backend event stream.
 *
 * Backend method names arrive space-separated (`shell_exec` ->
 * "shell exec", see `app/utils/listen/toolkit_listen.py:_get_context`), and
 * toolkit names are `inflection.titleize`d class names ("File Toolkit",
 * "Search Toolkit", "Terminal Toolkit") except the browser toolkit, which
 * hardcodes "Browser Toolkit" with all methods prefixed `browser_*`. This
 * classifier matches on those literal shapes.
 */

import type {
  MessageItem,
  TimelineItem,
  ToolItem,
} from '@/components/ChatBox/MessageItem/workLogTimeline';

export type ActivityCategory =
  | 'search'
  | 'edit'
  | 'shell'
  | 'browser'
  | 'read'
  | 'memory'
  | 'mcp'
  | 'other';

export interface ActivityItem {
  id: string;
  category: ActivityCategory;
  verb: string;
  object: string;
  badge?: string;
  running: boolean;
  /** Full file path (when this action targets a file) — for the click-to-open
   *  filename link. `object` is the shortened display name. */
  filePath?: string;
  /** Lines added/removed for an edit (parsed from a unified diff, or a full
   *  write's content). Rendered as a green +N / red -M badge. */
  diff?: { added: number; removed: number };
  /** Source tool's request/response, carried through for click-to-inspect. */
  input: string;
  output: string;
}

export interface ActivityGroup {
  id: string;
  summary: string;
  items: ActivityItem[];
}

export type ActivityRenderEntry =
  | { kind: 'message'; item: MessageItem }
  | { kind: 'activity-group'; group: ActivityGroup };

function extractParam(input: string, keys: string[]): string | null {
  for (const key of keys) {
    // key='val' or key="val" — also matches the first item of a quoted list,
    // e.g. file_paths=['README.md', …] → README.md.
    const match = input.match(
      new RegExp(`${key}\\s*=\\s*\\[?\\s*['"]([^'"]*)['"]`, 'i')
    );
    if (match) return match[1];
  }
  return null;
}

/** Common file-path argument keys the backend uses (singular + plural). */
const FILE_PATH_KEYS = [
  'file_path',
  'file_paths',
  'filename',
  'path',
  'paths',
  'filepath',
];

/**
 * Extract a file path from a tool input. Tries the known kwargs keys first, then
 * falls back to a loose match for the FileToolkit's narration form
 * ("write content to file: /abs/path with encoding: …") or a bare absolute path.
 */
function extractFilePath(input: string): string | null {
  const byKey = extractParam(input, FILE_PATH_KEYS);
  if (byKey) return byKey;
  const toFile = input.match(/to file:\s*([^\s'"]+)/i);
  if (toFile) return toFile[1];
  const bare = input.match(/(?:^|\s)(\/[^\s'"]+\.[A-Za-z0-9]+)/);
  return bare ? bare[1] : null;
}

function extractUrl(input: string): string | null {
  const match = input.match(/https?:\/\/[^\s'")]+/);
  return match ? match[0] : null;
}

function truncate(text: string, max: number): string {
  const trimmed = (text || '').trim();
  if (trimmed.length <= max) return trimmed;
  return `${trimmed.slice(0, max - 1)}…`;
}

/** Last path segment for a file path, or host+path for a URL. */
function shorten(value: string): string {
  if (!value) return value;
  if (/^https?:\/\//i.test(value)) {
    try {
      const url = new URL(value);
      return url.hostname + (url.pathname !== '/' ? url.pathname : '');
    } catch {
      return value;
    }
  }
  const parts = value.split(/[\\/]/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : value;
}

/** Parses a result count out of a tool's DEACTIVATE message, when present. */
function extractResultBadge(output: string): string | undefined {
  if (!output) return undefined;
  const match = output.match(/(\d+)\s*(results?|matches?|items?)/i);
  if (match) {
    const count = Number.parseInt(match[1], 10);
    if (count === 0) return 'no results';
    const noun = /result/i.test(match[2]) ? 'results' : match[2].toLowerCase();
    return `${count} ${noun}`;
  }
  try {
    const parsed = JSON.parse(output);
    if (Array.isArray(parsed)) {
      return parsed.length === 0 ? 'no results' : `${parsed.length} results`;
    }
  } catch {
    // Not JSON; no count to report.
  }
  return undefined;
}

/**
 * Turn an MCP tool method into a human label: strip a leading server/namespace
 * prefix if present, replace underscores/dashes with spaces, collapse spacing,
 * and Sentence-case. `list_customers` -> "List customers"; `afriex.get_rate` ->
 * "Get rate".
 */
function humanizeMcpMethod(method: string): string {
  const raw = (method || '').trim();
  const afterPrefix = raw.includes('.') ? raw.split('.').pop()! : raw;
  const words = afterPrefix
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (!words) return 'MCP action';
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function browserVerb(method: string): string {
  if (method.includes('visit') || method.includes('open')) return 'Visited';
  if (method.includes('click')) return 'Clicked';
  if (method.includes('type') || method.includes('enter')) return 'Typed';
  if (method.includes('scroll')) return 'Scrolled';
  if (method.includes('screenshot') || method.includes('snapshot'))
    return 'Viewed';
  if (method.includes('upload') || method.includes('download'))
    return 'Transferred';
  return 'Browsed';
}

/**
 * Workforce/session setup calls (`register agent`, `clone_for_new_session` -
 * see `PREPARATION_METHODS` in this same directory's accordion) are internal
 * plumbing, not user-visible activity. Classified as-is they'd mislabel a
 * browser-session clone as "Browsed <agent repr>", which never happened.
 */
const PREPARATION_METHOD_NAMES = new Set([
  'register agent',
  'clone for new session',
]);

/** Maps one paired tool call to a display-ready activity item. */
export function classifyToolItem(item: ToolItem): ActivityItem {
  const toolkit = item.toolkitName.toLowerCase();
  const method = item.method.toLowerCase();
  const running = item.status === 'running';

  let category: ActivityCategory = 'other';
  let verb = item.method || 'Ran';
  let object = item.toolkitName;
  let badge: string | undefined;

  if (PREPARATION_METHOD_NAMES.has(method)) {
    // category/verb/object stay at the neutral defaults above.
  } else if (
    method.includes('write') &&
    (method.includes('file') || method.includes('content'))
  ) {
    // File writes — incl. TerminalToolkit.shell_write_content_to_file, which
    // lives on the terminal toolkit but is a real file write (not a shell
    // command). Must come before the terminal/shell branch below.
    category = 'edit';
    verb = 'Wrote';
    object =
      extractFilePath(item.input) ||
      extractParam(item.input, ['file_path', 'filename', 'path']) ||
      'file';
  } else if (toolkit.includes('mcp')) {
    // MCP connector tool (MCPToolkit · e.g. list_customers, authenticate).
    // We can't enumerate every third-party tool, so just humanize the tool
    // name: drop underscores and Sentence-case it (list_customers ->
    // "List customers"). The connector icon signals it's an MCP action.
    category = 'mcp';
    verb = humanizeMcpMethod(item.method);
    object = '';
  } else if (toolkit.includes('terminal') || method.includes('shell')) {
    category = 'shell';
    verb = 'Ran';
    object =
      extractParam(item.input, ['command', 'cmd']) ||
      truncate(item.input, 60) ||
      'command';
  } else if (
    toolkit.includes('search') ||
    method.includes('search') ||
    method.includes('grep') ||
    method.includes('glob')
  ) {
    category = 'search';
    verb = method.includes('glob') ? 'Found files' : 'Searched';
    // File/code search tools use `pattern=`; web search uses `query=`.
    object =
      extractParam(item.input, [
        'query',
        'q',
        'pattern',
        'regex',
        'keyword',
        'search_term',
        'text',
      ]) ||
      truncate(item.input, 60) ||
      'the codebase';
    badge = extractResultBadge(item.output);
  } else if (toolkit.includes('browser')) {
    category = 'browser';
    verb = browserVerb(method);
    object =
      extractParam(item.input, ['url', 'ref', 'text', 'selector']) ||
      extractUrl(item.input) ||
      truncate(item.input, 40) ||
      'page';
  } else if (
    toolkit.includes('web') ||
    method.includes('fetch') ||
    method.includes('crawl')
  ) {
    // WebFetchToolkit · Web_fetch_and_analyze, etc.
    category = 'browser';
    verb = 'Fetched';
    object =
      extractUrl(item.input) ||
      extractParam(item.input, ['url', 'link']) ||
      truncate(item.input, 40) ||
      'page';
  } else if (toolkit.includes('skill')) {
    // SkillToolkit · Load_skill / List_skills / Search_skills
    category = 'other';
    if (method.includes('list')) {
      verb = 'Listed';
      object = 'skills';
    } else if (method.includes('load') || method.includes('use')) {
      verb = 'Loaded skill';
      object =
        extractParam(item.input, ['skill_name', 'name', 'skill']) || 'skill';
    } else {
      verb = 'Skill';
      object =
        extractParam(item.input, ['skill_name', 'name', 'skill']) || 'skill';
    }
  } else if (toolkit.includes('memory')) {
    // MemoryToolkit · remember_fact / recall_facts
    category = 'memory';
    if (method.includes('remember')) {
      verb = 'Remembered';
      object =
        extractParam(item.input, ['fact', 'text']) ||
        truncate(item.input, 60) ||
        'a fact';
    } else {
      verb = 'Recalled';
      object =
        extractParam(item.input, ['query', 'q']) ||
        truncate(item.input, 60) ||
        'from memory';
    }
  } else if (
    toolkit.includes('diff') ||
    method.includes('patch') ||
    method.includes('apply_diff')
  ) {
    // DiffToolkit · apply_patch(patch) — a unified diff (the surgical edit path).
    category = 'edit';
    verb = 'Edited';
    object =
      filePathFromPatch(extractParam(item.input, ['patch', 'diff'])) ||
      extractFilePath(item.input) ||
      'file';
  } else if (toolkit.includes('file') && method.includes('write')) {
    category = 'edit';
    verb = 'Wrote';
    object =
      extractFilePath(item.input) ||
      extractParam(item.input, ['filename', 'title']) ||
      'file';
  } else if (toolkit.includes('file') && method.includes('edit')) {
    category = 'edit';
    verb = 'Edited';
    object = extractFilePath(item.input) || 'file';
  } else if (method.includes('read')) {
    category = 'read';
    verb = 'Read file';
    object =
      extractFilePath(item.input) ||
      extractParam(item.input, ['image_path']) ||
      'file';
  } else if (method.includes('screenshot')) {
    category = 'read';
    verb = 'Viewed';
    object =
      extractParam(item.input, [...FILE_PATH_KEYS, 'image_path']) ||
      truncate(item.input, 40) ||
      'screenshot';
  } else if (method.includes('todo')) {
    verb = 'Updated';
    object = 'todo list';
  } else {
    object =
      extractParam(item.input, [...FILE_PATH_KEYS, 'name']) ||
      item.toolkitName;
  }

  // Capture the full file path for file-targeting actions so the trace can make
  // the filename a click-to-open link (object is just the shortened display).
  const filePath =
    category === 'read' || category === 'edit'
      ? extractFilePath(item.input) ??
        extractParam(item.input, ['image_path']) ??
        undefined
      : undefined;

  // Line add/remove stats for edits — from a unified diff, or a full write's
  // content (all additions). Rendered as a +N / -M badge.
  const diff =
    category === 'edit' ? extractDiffStats(item.input, method) : undefined;

  return {
    id: item.id,
    category,
    verb,
    object: shorten(object),
    badge,
    running,
    filePath,
    diff,
    input: item.input,
    output: item.output,
  };
}

/**
 * Split on line breaks, tolerating BOTH real newlines and the escaped `\n`
 * (backslash-n) that the backend's `key=repr(value)` narration produces.
 */
function splitLines(text: string): string[] {
  return text.split(/\\n|\r?\n/);
}

/** Count added/removed lines from a unified diff. */
function countDiffLines(patch: string): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const line of splitLines(patch)) {
    if (line.startsWith('+') && !line.startsWith('+++')) added += 1;
    else if (line.startsWith('-') && !line.startsWith('---')) removed += 1;
  }
  return { added, removed };
}

/** Extract the target path from a unified diff's `+++ b/<path>` header. */
function filePathFromPatch(patch: string | null): string | null {
  if (!patch) return null;
  const m = patch.match(/^\+\+\+\s+(?:b\/)?(.+)$/m);
  return m ? m[1].trim() : null;
}

/**
 * Best-effort line add/remove stats for an edit action: a unified diff if
 * present, otherwise a full write's content counts as additions. Returns
 * undefined when there's nothing meaningful to show.
 */
function extractDiffStats(
  input: string,
  method: string
): { added: number; removed: number } | undefined {
  // Explicit backend tag (e.g. write_to_file narration: "... [diff +12 -0]").
  // Most reliable — the raw content/patch is often narrated away or truncated.
  const tag = input.match(/\[diff\s*\+(\d+)\s*-(\d+)\]/i);
  if (tag) {
    const added = parseInt(tag[1], 10);
    const removed = parseInt(tag[2], 10);
    if (added || removed) return { added, removed };
  }
  const patch = extractParam(input, ['patch', 'diff']);
  if (patch && (patch.includes('@@') || /(^|\\n)[+-]/.test(patch))) {
    const stats = countDiffLines(patch);
    if (stats.added || stats.removed) return stats;
  }
  if (method.includes('write') || method.includes('create')) {
    const content = extractParam(input, ['content']);
    if (content) {
      const added = splitLines(content).filter((l) => l.length > 0).length;
      if (added) return { added, removed: 0 };
    }
  }
  return undefined;
}

const CATEGORY_NOUNS: Record<
  Exclude<ActivityCategory, 'other'>,
  [string, string]
> = {
  read: ['file viewed', 'files viewed'],
  edit: ['file written', 'files written'],
  search: ['search', 'searches'],
  browser: ['browser action', 'browser actions'],
  shell: ['command', 'commands'],
  memory: ['memory', 'memories'],
  mcp: ['connector action', 'connector actions'],
};

/** Counts per category, excluding 'other' (nothing meaningful to summarize). */
export function summarizeActivities(
  items: ActivityItem[]
): Record<Exclude<ActivityCategory, 'other'>, number> {
  const counts = {
    read: 0,
    edit: 0,
    search: 0,
    browser: 0,
    shell: 0,
    memory: 0,
  };
  for (const item of items) {
    if (item.category === 'other') continue;
    counts[item.category] += 1;
  }
  return counts;
}

/** Builds the "N searches, N files written" style summary line for a group. */
export function formatActivitySummary(items: ActivityItem[]): string {
  const counts = summarizeActivities(items);
  const parts: string[] = [];
  (Object.keys(counts) as Array<keyof typeof counts>).forEach((key) => {
    const count = counts[key];
    if (!count) return;
    const [singular, plural] = CATEGORY_NOUNS[key];
    parts.push(`${count} ${count === 1 ? singular : plural}`);
  });
  if (!parts.length) {
    return items.length === 1 ? items[0].object : `${items.length} actions`;
  }
  return parts.join(', ');
}

/**
 * Splits a chronological `TimelineItem[]` into render entries: message rows
 * pass through unchanged, and consecutive runs of tool calls (uninterrupted
 * by narration) collapse into one `ActivityGroup`.
 */
export function buildActivityRenderEntries(
  items: TimelineItem[]
): ActivityRenderEntry[] {
  const entries: ActivityRenderEntry[] = [];
  let buffer: ToolItem[] = [];

  const flush = () => {
    if (buffer.length === 0) return;
    const activityItems = buffer.map(classifyToolItem);
    entries.push({
      kind: 'activity-group',
      group: {
        id: `ag-${buffer[0].id}`,
        summary: formatActivitySummary(activityItems),
        items: activityItems,
      },
    });
    buffer = [];
  };

  for (const item of items) {
    if (item.kind === 'message') {
      flush();
      entries.push({ kind: 'message', item });
    } else {
      buffer.push(item);
    }
  }
  flush();

  return entries;
}

/**
 * The compact, humanized activity trace is now the DEFAULT rendering — the
 * product is an editor + agent (not standalone Eigent), so the Claude-Code /
 * Antigravity style trace is always on. Kept as a function so existing call
 * sites (TaskWorkLogAccordion) don't need to change.
 */
export function isActivityTraceEnabled(): boolean {
  return true;
}

export interface ChangedFile {
  path: string;
  diff?: { added: number; removed: number };
}

/**
 * Aggregate the files an agent CHANGED during a task, for the end-of-task
 * "Files changed" summary. Walks each agent's tool log, classifies every tool
 * call, and keeps the edit-category ones (write_to_file / apply_patch /
 * shell_write_content_to_file) deduped by path, carrying the last known diff.
 */
export function extractChangedFiles(
  agents: Array<{ log?: Array<{ data?: Record<string, unknown> }> }> | undefined
): ChangedFile[] {
  const byPath = new Map<string, ChangedFile>();
  let n = 0;
  for (const agent of agents ?? []) {
    for (const entry of agent?.log ?? []) {
      const data = entry?.data ?? {};
      const message = (data as { message?: unknown }).message;
      const item = classifyToolItem({
        kind: 'tool',
        id: `cf-${n++}`,
        toolkitName: String((data as { toolkit_name?: unknown }).toolkit_name ?? 'Tool'),
        method: String((data as { method_name?: unknown }).method_name ?? ''),
        input: typeof message === 'string' ? message : '',
        output: '',
        status: 'success',
      } as unknown as ToolItem);
      if (item.category === 'edit' && item.filePath) {
        const prev = byPath.get(item.filePath);
        byPath.set(item.filePath, {
          path: item.filePath,
          diff: item.diff ?? prev?.diff,
        });
      }
    }
  }
  return [...byPath.values()];
}
