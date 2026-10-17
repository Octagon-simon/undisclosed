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
import { AgentStep } from '@/types/constants';

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

/**
 * A search pattern that reads cleanly as a quoted term. Returns null for a
 * pattern that would render as noise — punctuation-only (`(`), or a heavy regex
 * (`export (const|function)`) — so callers fall back to a path or a generic
 * object instead of showing "Searched (".
 */
function cleanSearchTerm(raw: string | null): string | null {
  const term = (raw || '').trim().replace(/^['"]+|['"]+$/g, '').trim();
  if (!term) return null;
  if (!/[A-Za-z0-9]/.test(term)) return null; // punctuation-only
  const metaCount = (term.match(/[()[\]{}|\\^$*+?]/g) || []).length;
  if (metaCount >= 2) return null; // reads as a regex blob, not a term
  return truncate(term, 40);
}

/** A glob/name pattern for a file-name search — keep `*`, just strip quotes. */
function cleanGlob(raw: string | null): string | null {
  const g = (raw || '').trim().replace(/^['"]+|['"]+$/g, '').trim();
  if (!g || !/[A-Za-z0-9*]/.test(g)) return null;
  return g;
}

/**
 * Best-effort search pattern from a `grep`/`rg`/`ag`/`ack` command so a shell
 * search reads like a tool search ("Searched \"truncate\"") instead of the
 * generic "Searched files". Prefers the first QUOTED argument (patterns are
 * almost always quoted); returns null for unquoted/complex commands.
 */
function grepPatternFromCommand(command: string): string | null {
  const m = command.match(
    /\b(?:grep|egrep|fgrep|rg|ag|ack)\b[^\n]*?(['"])(.+?)\1/
  );
  return m ? m[2] : null;
}

/**
 * A `[N matches]`-style count badge (Antigravity's metric pill) from a tool's
 * DEACTIVATE message. CONSERVATIVE on purpose: the backend truncates tool output
 * to 500 chars, so we only trust an explicit count the tool itself printed, or a
 * (complete) JSON array — never a line-count of truncated text, which would
 * under-report. `preferredNoun` ("matches", "files", "sources") sets the label.
 */
function extractResultBadge(
  output: string,
  preferredNoun = 'results'
): string | undefined {
  if (!output) return undefined;
  const singular = preferredNoun.replace(/s$/, '');
  const match = output.match(/(\d+)\s*(results?|matches?|items?|files?)/i);
  if (match) {
    const count = Number.parseInt(match[1], 10);
    return count === 0 ? `no ${preferredNoun}` : `${count} ${count === 1 ? singular : preferredNoun}`;
  }
  try {
    const parsed = JSON.parse(output);
    if (Array.isArray(parsed)) {
      const n = parsed.length;
      return n === 0 ? `no ${preferredNoun}` : `${n} ${n === 1 ? singular : preferredNoun}`;
    }
  } catch {
    // Not JSON; no reliable count to report.
  }
  return undefined;
}

/** Extract an unquoted numeric kwarg (`start_line=10`), which `extractParam`
 *  (quoted-only) misses. */
function numParam(input: string, keys: string[]): number | null {
  for (const key of keys) {
    const m = input.match(new RegExp(`${key}\\s*=\\s*(\\d+)`, 'i'));
    if (m) return Number.parseInt(m[1], 10);
  }
  return null;
}

/** `lines X–Y` badge for a windowed file read, from the REQUEST args (accurate
 *  even though the returned content is truncated). Undefined for a whole-file
 *  read (no range args). */
function readRangeBadge(input: string): string | undefined {
  const start = numParam(input, ['start_line', 'startline', 'offset', 'start']);
  const end = numParam(input, ['end_line', 'endline', 'end']);
  const limit = numParam(input, ['limit']);
  if (start != null && end != null && end >= start) return `lines ${start}–${end}`;
  if (start != null && limit != null && limit > 0)
    return `lines ${start}–${start + limit - 1}`;
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

/** Human-friendly duration for a `sleep`/wait, e.g. 240 -> "4 min", 30 -> "30s". */
function formatDuration(totalSeconds: number): string {
  if (!Number.isFinite(totalSeconds) || totalSeconds <= 0) return 'a moment';
  if (totalSeconds < 60) return `${Math.round(totalSeconds)}s`;
  const minutes = Math.round(totalSeconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round((totalSeconds / 3600) * 10) / 10;
  return `${hours} hr`;
}

/** Parse a `sleep` argument (`240`, `1.5`, `2m`, `1h`) into seconds. */
function parseSleepSeconds(arg: string | undefined): number {
  if (!arg) return 0;
  const match = arg.match(/^([\d.]+)\s*([smhd]?)/i);
  if (!match) return 0;
  const value = Number.parseFloat(match[1]);
  if (!Number.isFinite(value)) return 0;
  const unit = match[2].toLowerCase();
  const factor =
    unit === 'm' ? 60 : unit === 'h' ? 3600 : unit === 'd' ? 86400 : 1;
  return value * factor;
}

/** Basename of a program path (`/usr/bin/python3` -> `python3`). */
function programBasename(token: string): string {
  return (token || '').replace(/^.*\//, '');
}

/** First token that looks like a file argument (has an extension), shortened. */
function firstFileArg(tokens: string[]): string | null {
  const file = tokens
    .slice(1)
    .find((t) => !t.startsWith('-') && /\.[A-Za-z0-9]+$/.test(t));
  return file ? shorten(file) : null;
}

/**
 * A segment that's just glue — `echo …`, `cd …`, `true`, or bare env
 * assignments (`FOO=bar`) — carries no real action, so we skip it when picking
 * the command to describe.
 */
function isTrivialSegment(seg: string): boolean {
  const s = seg.trim();
  if (!s) return true;
  if (/^(echo|printf|true|:|exit)\b/.test(s)) return true;
  if (/^cd\b/.test(s)) return true;
  if (/^(\w+=(?:'[^']*'|"[^"]*"|\S*)\s*)+$/.test(s)) return true; // pure FOO=bar
  return false;
}

/** Describe ONE command (already split off a pipeline) as verb + short object. */
function describeSingleCommand(seg: string): { verb: string; object: string } {
  // Strip leading env assignments (`FOO=bar cmd …`) so we read the real program.
  const effective =
    seg.replace(/^(?:\w+=(?:'[^']*'|"[^"]*"|\S+)\s+)+/, '').trim() || seg.trim();
  const tokens = effective.split(/\s+/).filter(Boolean);
  const prog = programBasename(tokens[0] || '');
  const arg1 = tokens[1] || '';

  switch (prog) {
    case 'sleep':
      return { verb: 'Waited', object: formatDuration(parseSleepSeconds(arg1)) };
    case 'grep':
    case 'egrep':
    case 'fgrep':
    case 'rg':
    case 'ag':
    case 'ack': {
      const term = cleanSearchTerm(grepPatternFromCommand(effective));
      return {
        verb: 'Searched',
        object: term ? `codebase for "${term}"` : 'codebase',
      };
    }
    case 'find':
    case 'fd':
      return { verb: 'Found files', object: 'in the workspace' };
    case 'ls':
    case 'll':
    case 'la':
    case 'tree':
    case 'dir':
      return { verb: 'Listed', object: 'files' };
    case 'cat':
    case 'head':
    case 'tail':
    case 'less':
    case 'more':
    case 'bat':
    case 'nl':
      return { verb: 'Read', object: firstFileArg(tokens) || 'a file' };
    case 'touch':
      return { verb: 'Created', object: firstFileArg(tokens) || 'a file' };
    case 'mkdir':
      return { verb: 'Created', object: 'a folder' };
    case 'rm':
    case 'rmdir':
      return { verb: 'Removed', object: firstFileArg(tokens) || 'files' };
    case 'cp':
      return { verb: 'Copied', object: 'files' };
    case 'mv':
      return { verb: 'Moved', object: 'files' };
    case 'curl':
    case 'wget':
    case 'http':
      return { verb: 'Fetched', object: extractUrl(effective) || 'a URL' };
    case 'git':
      return { verb: 'Ran', object: arg1 ? `git ${arg1}` : 'git' };
    case 'npm':
    case 'pnpm':
    case 'yarn':
    case 'bun':
    case 'pip':
    case 'pip3':
    case 'uv':
    case 'poetry':
    case 'docker':
    case 'kubectl':
    case 'make':
    case 'cargo':
      return { verb: 'Ran', object: arg1 ? `${prog} ${arg1}` : prog };
    case 'python':
    case 'python3':
    case 'node':
    case 'ruby':
    case 'go':
    case 'bash':
    case 'sh':
    case 'zsh':
      return { verb: 'Ran', object: firstFileArg(tokens) || `a ${prog} script` };
    case 'chmod':
    case 'chown':
      return { verb: 'Changed', object: 'permissions' };
    case 'kill':
    case 'pkill':
    case 'killall':
      return { verb: 'Stopped', object: 'a process' };
    case 'ps':
    case 'top':
    case 'htop':
    case 'jobs':
      return { verb: 'Checked', object: 'processes' };
    case 'which':
    case 'whereis':
    case 'type':
      return { verb: 'Located', object: arg1 ? shorten(arg1) : 'a program' };
    case 'awk':
    case 'sed':
      return { verb: 'Processed', object: 'text' };
    case 'wc':
      return { verb: 'Counted', object: 'lines' };
    case '':
      return { verb: 'Ran', object: 'a command' };
    default:
      return { verb: 'Ran', object: prog };
  }
}

/**
 * Turn a raw shell command into a short, friendly label instead of dumping the
 * command string. Splits pipelines/chains (`&&`, `||`, `|`, `;`), skips trivial
 * glue (`cd`, `echo`, env assignments), describes the primary real step, and
 * notes any extra steps as a badge. The raw command stays available via the
 * item's `input` (click-to-inspect).
 */
function describeShellCommand(rawCommand: string): {
  verb: string;
  object: string;
  badge?: string;
} {
  const command = (rawCommand || '').trim();
  if (!command) return { verb: 'Ran', object: 'a command' };

  const segments = command
    .split(/\s*(?:&&|\|\||[;|])\s*/)
    .map((s) => s.trim())
    .filter(Boolean);
  const meaningful = segments.filter((s) => !isTrivialSegment(s));
  const primary = meaningful[0] || segments[0] || command;

  const described = describeSingleCommand(primary);
  const extra = meaningful.length - 1;
  return {
    verb: described.verb,
    object: truncate(described.object, 48),
    badge: extra > 0 ? `+${extra} more` : undefined,
  };
}

/**
 * Tools are prompted to pass a human `message_title` / `message_description`
 * describing each call (see brain `app/agent/prompt.py`). When present, that
 * agent-authored summary is the friendliest label we can show — e.g. a Figma
 * read carries "Read Figma dropdown node", far better than "Read file / file".
 * Titles are written imperatively, so use the first word as the verb pill and
 * the rest as the object so it reads like the other activity rows.
 */
function labelFromNarration(
  input: string
): { verb: string; object: string } | null {
  const text = (
    extractParam(input, ['message_title', 'message_description']) || ''
  ).trim();
  if (!text) return null;
  const space = text.indexOf(' ');
  if (space === -1) return { verb: text, object: '' };
  return { verb: text.slice(0, space), object: text.slice(space + 1) };
}

/**
 * Past-tense verb → present-continuous, so a RUNNING row reads "Searching
 * codebase…" and flips to "Searched codebase" when done — matching Antigravity's
 * activity trace (see activity-antigravity.md §4D). Unmapped verbs (e.g. a
 * humanized MCP method) are left as-is while running.
 */
const PAST_TO_GERUND: Record<string, string> = {
  Searched: 'Searching',
  'Found files': 'Finding files',
  Read: 'Reading',
  'Read file': 'Reading file',
  Wrote: 'Writing',
  Edited: 'Editing',
  Updated: 'Updating',
  Created: 'Creating',
  Removed: 'Removing',
  Copied: 'Copying',
  Moved: 'Moving',
  Fetched: 'Fetching',
  Ran: 'Running',
  Listed: 'Listing',
  Waited: 'Waiting',
  Changed: 'Changing',
  Stopped: 'Stopping',
  Checked: 'Checking',
  Located: 'Locating',
  Processed: 'Processing',
  Counted: 'Counting',
  Viewed: 'Viewing',
  Remembered: 'Remembering',
  Recalled: 'Recalling',
  'Loaded skill': 'Loading skill',
  Visited: 'Visiting',
  Clicked: 'Clicking',
  Typed: 'Typing',
  Scrolled: 'Scrolling',
  Browsed: 'Browsing',
  Transferred: 'Transferring',
};

function toRunningVerb(verb: string): string {
  return PAST_TO_GERUND[verb] ?? verb;
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
    const command =
      extractParam(item.input, ['command', 'cmd']) || item.input || '';
    const described = describeShellCommand(command);
    verb = described.verb;
    object = described.object;
    badge = described.badge;
  } else if (
    toolkit.includes('search') ||
    method.includes('search') ||
    method.includes('grep') ||
    method.includes('glob')
  ) {
    category = 'search';
    // Label shape mirrors Antigravity's activity trace (see activity-antigravity.md):
    //   code   -> Searched codebase for "term"
    //   web    -> Searched the web for "term"
    //   glob   -> Found files  <glob>
    // and a bad/regex/empty pattern falls back to a clean scope instead of the
    // old meaningless "Searched (".
    if (method.includes('glob')) {
      verb = 'Found files';
      const glob = cleanGlob(
        extractParam(item.input, ['glob', 'glob_pattern', 'pattern'])
      );
      object = glob ? shorten(glob) : 'in the workspace';
      badge = extractResultBadge(item.output, 'files');
    } else {
      verb = 'Searched';
      const isWeb = toolkit.includes('web') || method.includes('web');
      const term = cleanSearchTerm(
        extractParam(item.input, [
          'query',
          'q',
          'pattern',
          'regex',
          'keyword',
          'search_term',
          'text',
        ])
      );
      const where = isWeb ? 'the web' : 'codebase';
      object = term ? `${where} for "${term}"` : where;
      badge = extractResultBadge(item.output, isWeb ? 'sources' : 'matches');
    }
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
    // "Read" + filename reads cleanly ("Read contextWindow.ts"); "Read file
    // contextWindow.ts" was redundant. Falls back to "Read file" when unnamed.
    const readPath =
      extractFilePath(item.input) || extractParam(item.input, ['image_path']);
    verb = 'Read';
    object = readPath || 'file';
    badge = readRangeBadge(item.input);
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

  // Prefer the agent's own message_title/description as the label — but not for
  // file rows, whose object is a click-to-open filename we must keep.
  const narrated = filePath ? null : labelFromNarration(item.input);
  if (narrated) {
    verb = narrated.verb;
    object = narrated.object;
  }

  return {
    id: item.id,
    category,
    // Present-continuous while running ("Searching…"), past tense when done.
    verb: running ? toRunningVerb(verb) : verb,
    // Search objects are already cleaned/shortened in-branch; re-`shorten`ing
    // would split a term on "/" and mangle it. Everything else shortens paths.
    object:
      narrated || category === 'search'
        ? truncate(object, 64)
        : shorten(object),
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
  const counts: Record<Exclude<ActivityCategory, 'other'>, number> = {
    read: 0,
    edit: 0,
    search: 0,
    browser: 0,
    shell: 0,
    memory: 0,
    mcp: 0,
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
 * product is an editor + agent (not standalone Undisclosed), so the Claude-Code /
 * Antigravity style trace is always on. Kept as a function so existing call
 * sites (TaskWorkLogAccordion) don't need to change.
 */
export function isActivityTraceEnabled(): boolean {
  return true;
}

export interface ChangedFile {
  path: string;
  diff?: { added: number; removed: number };
  /**
   * The raw unified patch for this edit, when the tool carried one (apply_patch
   * / diff toolkit). Used as an immediate inline-diff source so the Changed
   * Files row expands without waiting on the backend `git diff` fetch — and so
   * Storybook (no backend) can render a real diff. Live rows still prefer the
   * fetched patch, which also covers write/untracked files the classifier has no
   * patch text for.
   */
  patch?: string;
}

/**
 * Aggregate the files an agent CHANGED during a task, for the end-of-task
 * "Files changed" summary. Walks each agent's tool log, classifies every tool
 * call, and keeps the edit-category ones (write_to_file / apply_patch /
 * shell_write_content_to_file) deduped by path, carrying the last known diff.
 */
/** The shape of a task's `taskAssigning` entries this module reads from. */
type AgentLogs = Array<{
  log?: Array<{
    step?: string;
    data?: Record<string, unknown>;
  }>;
}>;

/**
 * Steps that mean "this agent's turn is over": no DEACTIVATE for its tools can
 * arrive after one of these. Used to settle orphaned running rows (see
 * `pairAgentToolCalls`).
 */
const TERMINAL_AGENT_STEPS: ReadonlySet<string> = new Set([
  AgentStep.DEACTIVATE_AGENT,
  AgentStep.AGENT_END,
  AgentStep.AGENT_SUMMARY_END,
  AgentStep.END,
  AgentStep.FAILED,
]);

/**
 * Fold an agent's raw chronological log into paired tool calls. The backend
 * pushes BOTH the request (`ACTIVATE_TOOLKIT`, `data.message` holds the args)
 * and the response (`DEACTIVATE_TOOLKIT`, `data.message` holds the result) as
 * separate entries; treating each as its own tool call produced two rows per
 * action and left every row's Response blank. Pair them by `toolkit::method`
 * exactly like `buildAgentBlocks` does in `TaskWorkLogAccordion`, so the
 * request lands in `input` and the response in `output`.
 */
function pairAgentToolCalls(agents: AgentLogs | undefined): ToolItem[] {
  const tools: ToolItem[] = [];
  const pending = new Map<string, ToolItem[]>();
  let n = 0;

  for (const agent of agents ?? []) {
    const log = agent?.log ?? [];
    const firstToolIndex = tools.length;
    let agentFinished = false;

    for (const entry of log) {
      const step = entry?.step;
      if (step && TERMINAL_AGENT_STEPS.has(step)) agentFinished = true;
      const data = entry?.data ?? {};
      const toolkitName = String(
        (data as { toolkit_name?: unknown }).toolkit_name ?? 'Tool'
      );
      const method = String(
        (data as { method_name?: unknown }).method_name ?? ''
      );
      const rawMessage = (data as { message?: unknown }).message;
      const text = typeof rawMessage === 'string' ? rawMessage : '';
      const key = `${toolkitName}::${method}`;

      // The DEACTIVATE half carries the tool's response; fold it into the
      // ACTIVATE row it pairs with instead of emitting a second, empty row.
      if (step === AgentStep.DEACTIVATE_TOOLKIT) {
        const stack = pending.get(key);
        let target = stack?.[stack.length - 1];
        if (!target || target.status !== 'running') {
          // No keyed match. The backend does not always echo the same
          // `toolkit_name`/`method_name` on the DEACTIVATE (it can be renamed,
          // emptied, or normalized away), so the strict `toolkit::method` key
          // misses and the ACTIVATE row would shimmer "still working" forever
          // with an empty Response. An agent issues its tools in order, so fall
          // back to the most recent still-running row from THIS agent — that is
          // the call this response belongs to.
          target = undefined;
          for (let i = tools.length - 1; i >= firstToolIndex; i--) {
            if (tools[i].status === 'running') {
              target = tools[i];
              break;
            }
          }
        }
        if (target) {
          target.status = 'done';
          target.output = [target.output, text]
            .filter(Boolean)
            .join('\n\n')
            .trim();
          target.detail = [target.detail, text]
            .filter(Boolean)
            .join('\n\n')
            .trim();
        }
        continue;
      }

      if (step !== AgentStep.ACTIVATE_TOOLKIT) continue;
      if (!method && !text) continue;
      // Workforce/session setup is not user-visible activity (matches the
      // work log, which routes these to its synthetic "Preparing agents" block).
      if (PREPARATION_METHOD_NAMES.has(method.trim().toLowerCase())) continue;

      const tool: ToolItem = {
        kind: 'tool',
        id: `log-${n++}`,
        rowTitle: `${toolkitName} · ${method}`,
        toolkitName,
        method,
        detail: text,
        input: text,
        output: '',
        status: 'running',
      };
      tools.push(tool);
      const stack = pending.get(key);
      if (stack) stack.push(tool);
      else pending.set(key, [tool]);
    }

    // A finished agent cannot have a tool still "running": its DEACTIVATE was
    // either never emitted (e.g. an unwrapped, non-@listen_toolkit tool that
    // raised) or dropped in transit. Settle those orphaned rows so they stop
    // shimmering "still working" forever with a blank Response.
    if (agentFinished) {
      for (let i = firstToolIndex; i < tools.length; i++) {
        if (tools[i].status === 'running') tools[i].status = 'done';
      }
    }
  }

  return tools;
}

/**
 * Walk every logged tool call an agent made and classify it. This is the shared
 * source for both the end-of-task summaries (changed files + execution summary):
 * the backend's raw log entries become `ActivityItem`s without a new event
 * stream. Private — call the two named collectors below.
 */
function classifyAgentLogs(agents: AgentLogs | undefined): ActivityItem[] {
  return pairAgentToolCalls(agents).map((tool) => classifyToolItem(tool));
}

/**
 * Every classified activity a task performed, in log order. Feeds the Execution
 * Summary (`executionMetricsFromActivities`) — counts per category, no new
 * backend work.
 */
export function collectTaskActivities(
  agents: AgentLogs | undefined,
  opts?: { settle?: boolean }
): ActivityItem[] {
  const items = classifyAgentLogs(agents);
  if (!opts?.settle) return items;
  // The backend never writes its terminal step (`DEACTIVATE_AGENT`) into
  // `taskAssigning[].log` — the store only pushes ACTIVATE/DEACTIVATE_TOOLKIT
  // entries there — so the in-log orphan settle in `pairAgentToolCalls` cannot
  // fire on its own. When the owning task is no longer live, force every row to
  // finished: any that is still "running" is an orphan (its DEACTIVATE was
  // dropped in transit) and must stop shimmering "still working". Same
  // task-level normalization the work log uses (`TaskWorkLogAccordion`).
  return items.map((item) => (item.running ? { ...item, running: false } : item));
}

/**
 * Trim an `ActivityItem` to the fields worth persisting alongside a turn.
 *
 * Keeps everything the summary row renders (verb/object/file link/badge/diff)
 * but drops the raw tool request/response, which can be entire files: a turn
 * file must stay small, and a restored row is read-only anyway (no expandable
 * detail, so `input`/`output` would only bloat the file). `running` is forced
 * false because a persisted turn is, by definition, no longer running.
 */
export function toPersistedActivity(item: ActivityItem): ActivityItem {
  return {
    id: item.id,
    category: item.category,
    verb: item.verb,
    object: item.object,
    badge: item.badge,
    running: false,
    filePath: item.filePath,
    diff: item.diff,
    input: '',
    output: '',
  };
}

/** Map `toPersistedActivity` over a task's classified activities, returning
 *  `undefined` for an empty list so callers can omit the field entirely. */
export function toPersistedActivities(
  items: ActivityItem[]
): ActivityItem[] | undefined {
  return items.length ? items.map(toPersistedActivity) : undefined;
}

export function extractChangedFiles(agents: AgentLogs | undefined): ChangedFile[] {
  const byPath = new Map<string, ChangedFile>();
  for (const item of classifyAgentLogs(agents)) {
    if (item.category === 'edit' && item.filePath) {
      const prev = byPath.get(item.filePath);
      const patch = extractParam(item.input, ['patch', 'diff']) || undefined;
      byPath.set(item.filePath, {
        path: item.filePath,
        diff: item.diff ?? prev?.diff,
        patch: patch ?? prev?.patch,
      });
    }
  }
  return [...byPath.values()];
}
