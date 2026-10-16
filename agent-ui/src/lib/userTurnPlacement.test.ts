// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { beforeEach, describe, expect, it } from 'vitest';
import {
  PlacedUserTurnRegistry,
  isReemittedUserTurn,
  placedUserTurns,
  resolveSourceUserTurnId,
} from './userTurnPlacement';

describe('isReemittedUserTurn', () => {
  let registry: PlacedUserTurnRegistry;

  beforeEach(() => {
    registry = new PlacedUserTurnRegistry();
  });

  // Regression 1 — "re-emitted confirm → one copy": a `confirmed` that
  // re-arrives for a turn whose id we already placed must be treated as a
  // re-emit and ignored, so the turn stays at exactly one copy.
  it('treats a confirm for an already-placed turn id as a re-emit', () => {
    registry.markPlaced('u2');
    const currentMessages = [
      { id: 'u1', role: 'user', content: 'hi' },
      { id: 'a1', role: 'agent', content: 'hello' },
      { id: 'u2', role: 'user', content: 'retry' },
    ];

    expect(
      isReemittedUserTurn({
        resolvedTurnId: 'u2',
        resolvedContent: 'retry',
        currentMessages,
        registry,
      })
    ).toBe(true);
  });

  // Same re-emit, but the agent's reply already landed, so the id no longer
  // resolves from `nextUserId`/the trailing message. The placed copy in the
  // current task is still recognised.
  it('detects a re-emit from the placed copy when the id no longer resolves', () => {
    registry.markPlaced('u2');
    const currentMessages = [
      { id: 'u2', role: 'user', content: 'retry' },
      { id: 'a2', role: 'agent', content: 'done' },
    ];

    expect(
      isReemittedUserTurn({
        resolvedTurnId: undefined,
        resolvedContent: 'retry',
        currentMessages,
        registry,
      })
    ).toBe(true);
  });

  // Regression 2 — "genuine second send with the same text, different id →
  // two copies". This is the case the old TEXT-keyed guard got wrong (it hid
  // the real repeat). The id-keyed guard must NOT collapse it.
  it('does NOT treat a genuine second send of the same text with a fresh id as a re-emit', () => {
    registry.markPlaced('u2'); // the previous turn ("retry") is already placed
    const currentMessages = [
      { id: 'u2', role: 'user', content: 'retry' },
      { id: 'a2', role: 'agent', content: 'done' },
      { id: 'u3', role: 'user', content: 'retry' }, // the new, genuine turn
    ];

    expect(
      isReemittedUserTurn({
        resolvedTurnId: 'u3',
        resolvedContent: 'retry',
        currentMessages,
        registry,
      })
    ).toBe(false);
  });

  it('treats an unplaced id as new even when the same text is already placed', () => {
    registry.markPlaced('u2');

    expect(
      isReemittedUserTurn({
        resolvedTurnId: 'u9',
        resolvedContent: 'retry',
        currentMessages: [{ id: 'u2', role: 'user', content: 'retry' }],
        registry,
      })
    ).toBe(false);
  });

  it('does not flag the first placement of a fresh id', () => {
    expect(
      isReemittedUserTurn({
        resolvedTurnId: 'u1',
        resolvedContent: 'hello',
        currentMessages: [{ id: 'u1', role: 'user', content: 'hello' }],
        registry,
      })
    ).toBe(false);
  });

  it('matches whitespace-normalised content when scanning placed copies', () => {
    registry.markPlaced('u2');

    expect(
      isReemittedUserTurn({
        resolvedTurnId: undefined,
        resolvedContent: 're try',
        currentMessages: [{ id: 'u2', role: 'user', content: '  re\n try ' }],
        registry,
      })
    ).toBe(true);
  });

  it('never matches on text alone when no id in the task is placed', () => {
    const currentMessages = [
      { id: 'u2', role: 'user', content: 'retry' },
      { id: 'a2', role: 'agent', content: 'done' },
    ];

    expect(
      isReemittedUserTurn({
        resolvedTurnId: undefined,
        resolvedContent: 'retry',
        currentMessages,
        registry,
      })
    ).toBe(false);
  });
});

describe('resolveSourceUserTurnId', () => {
  it('prefers the stable turn id', () => {
    expect(
      resolveSourceUserTurnId(
        [
          { id: 'u1', role: 'user', content: 'x' },
          { id: 'u2', role: 'user', content: 'y' },
        ],
        'u2',
        'y'
      )
    ).toBe('u2');
  });

  it('falls back to the trailing user turn when the id is not present', () => {
    expect(
      resolveSourceUserTurnId(
        [
          { id: 'u1', role: 'user', content: 'x' },
          { id: 'a1', role: 'agent', content: 'z' },
          { id: 'u2', role: 'user', content: '  y ' },
        ],
        'u9',
        'y'
      )
    ).toBe('u2');
  });

  it('returns undefined when there is no source copy to remove', () => {
    expect(
      resolveSourceUserTurnId(
        [{ id: 'a1', role: 'agent', content: 'done' }],
        'u9',
        'y'
      )
    ).toBeUndefined();
  });
});

describe('placedUserTurns singleton', () => {
  it('tracks placed ids and resets', () => {
    placedUserTurns.reset();
    expect(placedUserTurns.isPlaced('x')).toBe(false);
    placedUserTurns.markPlaced('x');
    expect(placedUserTurns.isPlaced('x')).toBe(true);
    placedUserTurns.reset();
    expect(placedUserTurns.isPlaced('x')).toBe(false);
  });
});
