// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

/**
 * The host's key guard runs in window capture, ahead of anything bound inside
 * the panel, so it cannot let Cmd/Ctrl+Z through to the chatbox as a keydown.
 * It dispatches this cancelable event on the focused node instead; if the
 * chatbox claims it (preventDefault) the guard swallows the native chord.
 */
export const CHAT_HISTORY_EVENT = 'undisclosed:chat-history';

export interface ChatHistoryRequest {
  redo: boolean;
}

export interface HistoryEntry {
  value: string;
  caret: number;
}

type TypingRun = { kind: 'insert' | 'delete'; caret: number; at: number };

export interface ChatHistory {
  entries: HistoryEntry[];
  index: number;
  run: TypingRun | null;
}

export const HISTORY_LIMIT = 200;
export const TYPING_RUN_MS = 600;

/** Single contiguous edit turning `prev` into `next`. */
function describeEdit(prev: string, next: string) {
  let start = 0;
  const shortest = Math.min(prev.length, next.length);
  while (start < shortest && prev[start] === next[start]) start += 1;
  let prevEnd = prev.length;
  let nextEnd = next.length;
  while (
    prevEnd > start &&
    nextEnd > start &&
    prev[prevEnd - 1] === next[nextEnd - 1]
  ) {
    prevEnd -= 1;
    nextEnd -= 1;
  }
  return { at: start, removed: prevEnd - start, inserted: nextEnd - start };
}

export function createChatHistory(initial = ''): ChatHistory {
  return {
    entries: [{ value: initial, caret: initial.length }],
    index: 0,
    run: null,
  };
}

/**
 * Appends an edit. Consecutive single-character edits at a contiguous caret
 * collapse into one entry so undo steps by word rather than by keystroke; a
 * space (or `breakRun`) closes the run.
 */
export function recordChatHistory(
  history: ChatHistory,
  nextValue: string,
  caret: number,
  options: { breakRun?: boolean; now?: number } = {},
): void {
  const current = history.entries[history.index];
  if (!current || current.value === nextValue) return;
  const now = options.now ?? Date.now();

  const edit = describeEdit(current.value, nextValue);
  const single =
    (edit.inserted === 1 && edit.removed === 0) ||
    (edit.removed === 1 && edit.inserted === 0);
  const kind: TypingRun['kind'] = edit.inserted === 1 ? 'insert' : 'delete';
  const run = history.run;
  const continues =
    !options.breakRun &&
    single &&
    run !== null &&
    run.kind === kind &&
    now - run.at <= TYPING_RUN_MS &&
    // adjacent to the previous edit: typing moves the caret right, backspace left
    edit.at === current.caret - edit.removed &&
    caret === edit.at + edit.inserted;

  if (continues) {
    history.entries[history.index] = { value: nextValue, caret };
    const touched =
      nextValue.slice(edit.at, edit.at + edit.inserted) ||
      current.value.slice(edit.at, edit.at + edit.removed);
    history.run = /\s/.test(touched) ? null : { kind, caret, at: now };
    return;
  }

  history.entries.length = history.index + 1;
  history.entries.push({ value: nextValue, caret });
  history.index = history.entries.length - 1;
  if (history.entries.length > HISTORY_LIMIT) {
    history.entries.shift();
    history.index -= 1;
  }
  history.run = single ? { kind, caret, at: now } : null;
}

export function undoChatHistory(history: ChatHistory): HistoryEntry | null {
  if (history.index <= 0) return null;
  history.index -= 1;
  history.run = null;
  return history.entries[history.index];
}

export function redoChatHistory(history: ChatHistory): HistoryEntry | null {
  if (history.index >= history.entries.length - 1) return null;
  history.index += 1;
  history.run = null;
  return history.entries[history.index];
}
