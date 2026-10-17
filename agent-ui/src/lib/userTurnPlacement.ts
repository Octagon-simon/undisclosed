// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

/**
 * Option D — in-memory, ID-keyed placement guard for user turns.
 *
 * A single logical user turn can transiently live in two tasks at once. When a
 * follow-up is migrated out of the task it was optimistically added to and into
 * the fresh task created by the `confirmed` event, a late notice /
 * acknowledgement / the previous turn's `end` (or a re-emitted `confirmed` from
 * a re-attached stream) can leave a copy behind in BOTH tasks. Because the
 * conversation renders — and the export prints — one section per task, the same
 * turn then shows up twice.
 *
 * The earlier fix keyed the guard on the turn's TEXT ("the same user text with
 * no agent turn between can never be a legitimate repeat"). That is wrong: a
 * user CAN legitimately re-send the same text ("retry", "continue", "yes").
 * Hiding by text therefore swaps a duplicate for a *disappearing* message.
 *
 * This module keys on the turn's stable ID instead — the id minted by
 * `ChatBox.handleSend` (`nextUserId`) and reused wherever the turn is
 * (re)placed. A re-emitted event for an id we have already placed is ignored; a
 * genuine second send has a fresh id (and is therefore placed as its own turn),
 * even when its text is identical to an earlier turn.
 */

import { normalizeUserTurnContent } from './dedupeUserTurns';

export interface PlacementUserMessage {
  id?: string;
  role?: string;
  content?: unknown;
}

/**
 * Record of user-turn ids already placed in their FINAL task. Seeded only on an
 * actual placement (never on every confirm), so it can't swallow a real turn.
 *
 * It is deliberately in-memory: the durable turn store is single-copy anyway,
 * so a reload rehydrates clean, and this keeps the hottest path (a `confirmed`
 * arriving mid-stream) from doing any disk read.
 */
export class PlacedUserTurnRegistry {
  private readonly placed = new Set<string>();

  markPlaced(turnId: string | undefined | null): void {
    if (turnId) this.placed.add(turnId);
  }

  isPlaced(turnId: string | undefined | null): boolean {
    return !!turnId && this.placed.has(turnId);
  }

  reset(): void {
    this.placed.clear();
  }
}

/** Shared registry used by the chat store. */
export const placedUserTurns = new PlacedUserTurnRegistry();

export interface IsReemittedUserTurnParams {
  /**
   * The turn id resolved from the source task: its `nextUserId`, else the id of
   * the trailing optimistic user message. `undefined` when NEITHER exists — a
   * pure replay with no source turn to carry over. A genuine second send always
   * resolves an id here (handleSend mints `nextUserId` and, for an idle turn,
   * also adds the optimistic bubble), which is what keeps the text fallback
   * below from ever hiding it.
   */
  resolvedTurnId?: string;
  /** The user prompt this event resolves to. */
  resolvedContent: string;
  /** Messages currently in the task the event arrived for. */
  currentMessages: readonly PlacementUserMessage[];
  registry: PlacedUserTurnRegistry;
}

/**
 * True when this `confirmed`/`wait_confirm` is a re-emit of a turn already
 * placed, and should therefore be ignored rather than placed again.
 *
 * 1. If the turn id resolves, the answer is purely "have I placed this id?" —
 *    no text comparison at all.
 * 2. Only when the id can NOT be resolved (the turn already migrated, so its
 *    `nextUserId` is gone and the trailing message is the agent's reply) do we
 *    fall back to locating a user message in the current task whose ID is
 *    already placed and whose content matches. Because that fallback requires a
 *    *placed id*, it can only suppress a copy of a turn we already know about;
 *    it can never hide a genuine new turn.
 */
export function isReemittedUserTurn({
  resolvedTurnId,
  resolvedContent,
  currentMessages,
  registry,
}: IsReemittedUserTurnParams): boolean {
  if (resolvedTurnId) {
    return registry.isPlaced(resolvedTurnId);
  }

  const target = normalizeUserTurnContent(resolvedContent);
  if (!target) return false;

  return currentMessages.some(
    (message) =>
      message.role === 'user' &&
      registry.isPlaced(message.id) &&
      normalizeUserTurnContent(message.content) === target
  );
}

/**
 * Resolve which source message (if any) must be removed when a turn is migrated
 * into its final task. Prefers the stable id; falls back to the trailing user
 * message only when its (normalised) text matches, so a re-attached stream
 * cannot strand the bubble by leaving it off the end.
 */
export function resolveSourceUserTurnId(
  messages: readonly PlacementUserMessage[] | undefined,
  turnId: string,
  content: string
): string | undefined {
  const list = messages ?? [];
  const byId = list.find(
    (message) => message.role === 'user' && message.id === turnId
  );
  if (byId?.id) return byId.id;

  const last = list.at(-1);
  if (
    last?.role === 'user' &&
    last.id &&
    normalizeUserTurnContent(last.content) === normalizeUserTurnContent(content)
  ) {
    return last.id;
  }

  return undefined;
}
