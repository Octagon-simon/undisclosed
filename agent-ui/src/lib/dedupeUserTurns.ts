// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

/**
 * Guards against a single logical user turn being rendered (and exported)
 * twice.
 *
 * A user turn can transiently live in two tasks at once. When a follow-up is
 * migrated out of the task it was optimistically added to and into the fresh
 * task created by the `confirmed` event, a late notice / acknowledgement / the
 * previous turn's `end` (or a re-emitted `confirmed` from a re-attached stream)
 * can leave a copy behind in BOTH tasks. Because the conversation renders — and
 * the export prints — one section per task, the same turn then shows up twice.
 *
 * The duplicate signature is exact and safe to key on: two user turns with the
 * SAME text and NO agent turn between them. A user can never legitimately send
 * the same prompt twice with no reply in between, so collapsing that pattern
 * can never drop a real turn. A genuine repeat of the same text always has the
 * agent's answer separating the two, which resets the window.
 */

/** Collapse whitespace so trivial formatting differences don't defeat the match. */
export function normalizeUserTurnContent(content: unknown): string {
  if (typeof content !== 'string') return '';
  return content.replace(/\s+/g, ' ').trim();
}

export interface UserTurnMessage {
  id?: string;
  role?: string;
  content?: unknown;
}

export interface UserTurnSection {
  taskId: string;
  messages: readonly UserTurnMessage[] | undefined | null;
}

/**
 * Walk the ordered conversation (task sections in the order they render) and
 * return the set of user-message ids that are consecutive duplicates of a turn
 * already seen since the last agent message.
 *
 * Only the SECOND+ occurrence is added to the returned set, so callers hide the
 * later copy and keep the first (the one whose task the turn actually ran in).
 */
export function collectDuplicateUserTurnIds(
  sections: readonly UserTurnSection[]
): Set<string> {
  const duplicates = new Set<string>();
  let lastUserContent: string | null = null;
  let sawAgentSinceUser = false;

  for (const section of sections) {
    const messages = section?.messages ?? [];
    for (const message of messages) {
      if (!message || !message.content) continue;
      const content = normalizeUserTurnContent(message.content);
      if (!content) continue;

      if (message.role === 'user') {
        if (!sawAgentSinceUser && lastUserContent === content) {
          if (message.id) duplicates.add(message.id);
          continue;
        }
        lastUserContent = content;
        sawAgentSinceUser = false;
      } else if (message.role === 'agent') {
        sawAgentSinceUser = true;
      }
    }
  }

  return duplicates;
}
