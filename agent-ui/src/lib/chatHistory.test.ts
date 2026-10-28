// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { describe, expect, it } from 'vitest';
import {
  HISTORY_LIMIT,
  createChatHistory,
  recordChatHistory,
  redoChatHistory,
  undoChatHistory,
} from './chatHistory';

/** Feeds a whole string the way a user would type it, one char at a time. */
function type(history: ReturnType<typeof createChatHistory>, text: string, at = 0) {
  let value = history.entries[history.index].value;
  let caret = at;
  for (const char of text) {
    value = value.slice(0, caret) + char + value.slice(caret);
    caret += 1;
    recordChatHistory(history, value, caret, { now: 1000 });
  }
}

describe('chatHistory', () => {
  it('groups a typed word into one undo step', () => {
    const history = createChatHistory();
    type(history, 'hello');

    expect(history.entries).toHaveLength(2);
    expect(undoChatHistory(history)).toEqual({ value: '', caret: 0 });
    expect(undoChatHistory(history)).toBeNull();
  });

  it('closes the run on a space so undo steps by word', () => {
    const history = createChatHistory();
    type(history, 'hello world');

    expect(history.entries.map((e) => e.value)).toEqual([
      '',
      'hello ',
      'hello world',
    ]);
    expect(undoChatHistory(history)?.value).toBe('hello ');
    expect(undoChatHistory(history)?.value).toBe('');
  });

  it('groups consecutive backspaces', () => {
    const history = createChatHistory();
    history.index = 0;
    recordChatHistory(history, 'abc', 3, { breakRun: true });

    recordChatHistory(history, 'ab', 2, { now: 1000 });
    recordChatHistory(history, 'a', 1, { now: 1100 });

    expect(history.entries.map((e) => e.value)).toEqual(['', 'abc', 'a']);
    expect(undoChatHistory(history)).toEqual({ value: 'abc', caret: 3 });
  });

  it('does not group edits that are not adjacent', () => {
    const history = createChatHistory();
    type(history, 'a');

    // Typed a char at the end after moving the caret somewhere else.
    recordChatHistory(history, 'aX', 1, { now: 1000 });

    expect(history.entries.map((e) => e.value)).toEqual(['', 'a', 'aX']);
  });

  it('breaks a run after a pause', () => {
    const history = createChatHistory();
    recordChatHistory(history, 'a', 1, { now: 1000 });
    recordChatHistory(history, 'ab', 2, { now: 5000 });

    expect(history.entries.map((e) => e.value)).toEqual(['', 'a', 'ab']);
  });

  it('walks back and forward through entries', () => {
    const history = createChatHistory();
    recordChatHistory(history, 'one', 3, { breakRun: true });
    recordChatHistory(history, 'one two', 7, { breakRun: true });

    expect(undoChatHistory(history)?.value).toBe('one');
    expect(undoChatHistory(history)?.value).toBe('');
    expect(undoChatHistory(history)).toBeNull();

    expect(redoChatHistory(history)?.value).toBe('one');
    expect(redoChatHistory(history)?.value).toBe('one two');
    expect(redoChatHistory(history)).toBeNull();
  });

  it('drops redo entries once a new edit lands', () => {
    const history = createChatHistory();
    recordChatHistory(history, 'one', 3, { breakRun: true });
    recordChatHistory(history, 'two', 3, { breakRun: true });
    undoChatHistory(history);

    recordChatHistory(history, 'other', 5, { breakRun: true });

    expect(redoChatHistory(history)).toBeNull();
    expect(undoChatHistory(history)?.value).toBe('one');
  });

  it('caps how many steps it keeps', () => {
    const history = createChatHistory();
    for (let i = 1; i <= HISTORY_LIMIT + 5; i += 1) {
      recordChatHistory(history, 'x'.repeat(i), i, { breakRun: true });
    }

    expect(history.entries).toHaveLength(HISTORY_LIMIT);
    expect(history.index).toBe(HISTORY_LIMIT - 1);
  });
});
