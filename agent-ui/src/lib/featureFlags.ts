// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
// ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========

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
