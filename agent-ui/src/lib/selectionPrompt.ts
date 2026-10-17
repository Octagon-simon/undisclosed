// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import type { ComposerSelection } from '@/agent-embed/composerDraft';

export function baseName(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

/** Ascending 1-based range label: `L111` for one line, `L111-154` for many. */
export function formatLineRange(startLine: number, endLine: number): string {
  const start = Math.min(startLine, endLine);
  const end = Math.max(startLine, endLine);
  return start === end ? `L${start}` : `L${start}-${end}`;
}

/** Human label for a selection with no user text, e.g. `App.tsx L12-30`. */
export function selectionLabel(selection: ComposerSelection): string {
  return `${baseName(selection.path)} ${formatLineRange(
    selection.startLine,
    selection.endLine
  )}`;
}

/** Reference prepended to the user's text; the agent reads the file itself. */
export function buildSelectionPrompt(selection: ComposerSelection): string {
  const start = Math.min(selection.startLine, selection.endLine);
  const end = Math.max(selection.startLine, selection.endLine);
  const location = start === end ? `line ${start}` : `lines ${start}-${end}`;
  return `From ${selection.path} (${location}):\n\n`;
}
