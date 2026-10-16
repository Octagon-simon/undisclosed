// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

import { describe, expect, it } from 'vitest';
import { createChatStoreInstance } from './chatStore';
import type { Message } from './chatStore';

const userMessage = (id: string, content: string): Message =>
  ({ id, role: 'user', content }) as Message;

/**
 * Option D, guard 2 — the migration must remove the source copy and place the
 * destination copy in a SINGLE store update. These drive the real store so the
 * atomicity is exercised, not just described.
 */
describe('addMessages removeSource (turn migration)', () => {
  it('moves a user turn into its final task with no copy left behind', () => {
    const store = createChatStoreInstance();
    store.getState().create('task_src');
    store.getState().create('task_dst');

    store
      .getState()
      .addMessages('task_src', userMessage('u2', 'retry'));
    store
      .getState()
      .addMessages('task_src', { id: 'a1', role: 'agent', content: 'done' } as Message);

    // Migrate: remove the source copy and append the destination copy at once.
    store.getState().addMessages('task_dst', userMessage('u2', 'retry'), {
      removeSource: { taskId: 'task_src', messageId: 'u2' },
    });

    const src = store.getState().tasks.task_src.messages;
    const dst = store.getState().tasks.task_dst.messages;

    // Source no longer carries the user turn; the agent reply is untouched.
    expect(src.map((m) => m.id)).toEqual(['a1']);
    // Destination carries exactly one copy of the turn.
    expect(dst.filter((m) => m.id === 'u2')).toHaveLength(1);
    // Across both tasks there is exactly one copy (one section per task).
    const copies = [...src, ...dst].filter(
      (m) => m.role === 'user' && m.id === 'u2'
    );
    expect(copies).toHaveLength(1);
  });

  it('is a no-op removal when the source task or message is absent', () => {
    const store = createChatStoreInstance();
    store.getState().create('task_dst');

    store.getState().addMessages('task_dst', userMessage('u1', 'hello'), {
      removeSource: { taskId: 'task_missing', messageId: 'u1' },
    });

    expect(store.getState().tasks.task_dst.messages).toHaveLength(1);
  });
});
