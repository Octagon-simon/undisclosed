// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

// Optional bridge to the desktop shell's attention alert (Dock bounce + native
// notification). The Theia preload exposes `window.undisclosedAttention`; in a
// plain browser or the standalone shell the calls are no-ops, so the shared UI
// stays host-agnostic.

export type AttentionKind = 'question' | 'approval';

export interface AgentAttentionRequest {
  id: string;
  taskId: string;
  kind: AttentionKind;
  title: string;
  body: string;
}

interface AttentionBridge {
  request: (request: AgentAttentionRequest) => void;
  clear: (id: string) => void;
}

function bridge(): AttentionBridge | null {
  const candidate = (window as unknown as {
    undisclosedAttention?: Partial<AttentionBridge>;
  }).undisclosedAttention;
  if (
    candidate &&
    typeof candidate.request === 'function' &&
    typeof candidate.clear === 'function'
  ) {
    return candidate as AttentionBridge;
  }
  return null;
}

/** Stable id for one prompt: re-rendering the same ask must not re-alert. */
export function attentionPromptId(
  taskId: string,
  kind: AttentionKind,
  key: string
): string {
  return `${taskId}:${kind}:${key}`;
}

/** Ask the desktop shell for the user's attention. Never throws. */
export function requestAgentAttention(request: AgentAttentionRequest): void {
  try {
    bridge()?.request(request);
  } catch {
    // A broken bridge must never break the chat stream.
  }
}

/** Retire the alert for one prompt (answered, dismissed, run finished). */
export function clearAgentAttention(id: string): void {
  try {
    bridge()?.clear(id);
  } catch {
    // ignore
  }
}

/** Collapse whitespace and cut a prompt down to notification length. */
export function previewText(text: string | null | undefined, max = 160): string {
  const flat = (text ?? '').replace(/\s+/g, ' ').trim();
  return flat.length > max ? `${flat.slice(0, max - 1)}…` : flat;
}
