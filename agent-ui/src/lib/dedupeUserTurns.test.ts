// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { describe, expect, it } from 'vitest';
import {
  collectDuplicateUserTurnIds,
  normalizeUserTurnContent,
} from './dedupeUserTurns';

describe('normalizeUserTurnContent', () => {
  it('collapses whitespace and trims', () => {
    expect(normalizeUserTurnContent('  hello\n  world  ')).toBe('hello world');
  });

  it('returns empty string for non-strings', () => {
    expect(normalizeUserTurnContent(undefined)).toBe('');
    expect(normalizeUserTurnContent(42)).toBe('');
  });
});

describe('collectDuplicateUserTurnIds', () => {
  it('flags a user turn left behind in two tasks (the duplicated bubble)', () => {
    // T1 ends with the optimistic follow-up; T2 was created for it with a copy.
    const dupes = collectDuplicateUserTurnIds([
      {
        taskId: 't1',
        messages: [
          { id: 'u1', role: 'user', content: 'first' },
          { id: 'a1', role: 'agent', content: 'reply one' },
          { id: 'u2', role: 'user', content: 'yes make the cuts' },
        ],
      },
      {
        taskId: 't2',
        messages: [
          { id: 'u2-copy', role: 'user', content: 'yes make the cuts' },
          { id: 'a2', role: 'agent', content: 'reply two' },
        ],
      },
    ]);

    expect([...dupes]).toEqual(['u2-copy']);
    // The first occurrence is never hidden.
    expect(dupes.has('u2')).toBe(false);
  });

  it('does NOT flag a genuine repeat separated by an agent turn', () => {
    const dupes = collectDuplicateUserTurnIds([
      {
        taskId: 't1',
        messages: [
          { id: 'u1', role: 'user', content: 'run the tests' },
          { id: 'a1', role: 'agent', content: 'done' },
        ],
      },
      {
        taskId: 't2',
        messages: [
          { id: 'u2', role: 'user', content: 'run the tests' },
          { id: 'a2', role: 'agent', content: 'done again' },
        ],
      },
    ]);

    expect(dupes.size).toBe(0);
  });

  it('flags a consecutive duplicate within a single task', () => {
    const dupes = collectDuplicateUserTurnIds([
      {
        taskId: 't1',
        messages: [
          { id: 'u1', role: 'user', content: 'same' },
          { id: 'u2', role: 'user', content: 'same' },
        ],
      },
    ]);

    expect([...dupes]).toEqual(['u2']);
  });

  it('matches across trivial whitespace differences', () => {
    const dupes = collectDuplicateUserTurnIds([
      {
        taskId: 't1',
        messages: [{ id: 'u1', role: 'user', content: 'hello world' }],
      },
      {
        taskId: 't2',
        messages: [{ id: 'u2', role: 'user', content: '  hello\n  world ' }],
      },
    ]);

    expect([...dupes]).toEqual(['u2']);
  });

  it('does not flag distinct prompts', () => {
    const dupes = collectDuplicateUserTurnIds([
      {
        taskId: 't1',
        messages: [{ id: 'u1', role: 'user', content: 'one' }],
      },
      {
        taskId: 't2',
        messages: [{ id: 'u2', role: 'user', content: 'two' }],
      },
    ]);

    expect(dupes.size).toBe(0);
  });
});
