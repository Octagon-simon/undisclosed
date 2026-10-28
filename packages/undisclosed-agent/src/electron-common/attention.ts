// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

// Contract shared by the renderer preload bridge and the Electron main process.
// Both bundles import this, so the channel names and the payload shape cannot
// drift apart.

/** Renderer -> main: a blocking prompt (question or tool approval) just appeared. */
export const ATTENTION_REQUEST_CHANNEL = 'undisclosed:attention-request';
/** Renderer -> main: that prompt was answered / dismissed. */
export const ATTENTION_CLEAR_CHANNEL = 'undisclosed:attention-clear';

export type AttentionKind = 'question' | 'approval';

export interface AgentAttentionRequest {
  /** Stable per prompt so a repeated event cannot bounce twice. */
  id: string;
  taskId: string;
  kind: AttentionKind;
  title: string;
  body: string;
}

export const MAX_ATTENTION_ID = 200;
export const MAX_ATTENTION_TITLE = 80;
export const MAX_ATTENTION_BODY = 200;

const CONTROL_CHARS = /[\u0000-\u001f\u007f]+/g;

function clampText(value: unknown, max: number): string {
  if (typeof value !== 'string') {
    return '';
  }
  return value.replace(CONTROL_CHARS, ' ').replace(/\s+/g, ' ').trim().slice(0, max);
}

/**
 * Validate a payload that crossed the process boundary. Returns undefined for
 * anything that is not a well-formed request, so the main process never renders
 * unvalidated renderer text in a native notification.
 */
export function sanitizeAttentionRequest(
  raw: unknown
): AgentAttentionRequest | undefined {
  if (!raw || typeof raw !== 'object') {
    return undefined;
  }
  const candidate = raw as Partial<Record<keyof AgentAttentionRequest, unknown>>;
  const id = clampText(candidate.id, MAX_ATTENTION_ID);
  const taskId = clampText(candidate.taskId, MAX_ATTENTION_ID);
  const kind = candidate.kind;
  if (!id || !taskId || (kind !== 'question' && kind !== 'approval')) {
    return undefined;
  }
  const title = clampText(candidate.title, MAX_ATTENTION_TITLE);
  const body = clampText(candidate.body, MAX_ATTENTION_BODY);
  return {
    id,
    taskId,
    kind,
    title: title || 'Undisclosed needs your attention',
    body: body || 'The agent is waiting for your reply.',
  };
}

/** Validate the id sent on the clear channel. */
export function sanitizeAttentionId(raw: unknown): string | undefined {
  const id = clampText(raw, MAX_ATTENTION_ID);
  return id || undefined;
}
