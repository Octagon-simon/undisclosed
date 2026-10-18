// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

/**
 * Build-time feature flags. Vite inlines `import.meta.env` at build time, so
 * changing a flag requires a rebuild of the agent UI / embed bundle.
 */

/** Accepts the same spellings as the other build flags: true / 1 / on. */
export function parseFlag(value: unknown): boolean {
  if (typeof value !== 'string') return false;
  const normalized = value.trim().toLowerCase();
  return normalized === 'true' || normalized === '1' || normalized === 'on';
}

/**
 * Multi-agent workforce mode in the chat composer. Off by default: the agent
 * selection stays on single agent, and a Project persisted as workforce opens
 * in single-agent mode instead of switching the composer.
 */
export const WORKFORCE_MODE_ENABLED = parseFlag(
  import.meta.env.VITE_ENABLE_WORKFORCE_MODE
);

/**
 * Ask-to-approve governance gate for mutating tools. Off by default: the gate
 * works for terminal, file, git, GitHub, MongoDB and diff writes, but it is not
 * finished enough to expose. While off, every turn runs in Auto and the
 * approve toggle, the panel badge and the Ask/Auto menu entries are hidden.
 */
export const GOVERNANCE_MODE_ENABLED = parseFlag(
  import.meta.env.VITE_ENABLE_GOVERNANCE_MODE
);
