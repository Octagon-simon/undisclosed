// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

/**
 * Long file paths in a narrow row: keep the file name, elide the front.
 *
 * Ported from lacuna's coverage spinner, which cuts a path to
 * `'…' + path.slice(-n)` so the tail the reader is looking for survives the
 * clamp. Here the cut lands on a segment boundary, so the head reads
 * `…/steps/__tests__/` instead of `…ignWizard/steps/__tests__/`.
 */

/** Chars the whole label may take, elided head plus file name. */
export const PATH_BUDGET = 46;

export interface PathLabel {
  /** Elided directory prefix ending in `/`, or empty when nothing was cut. */
  head: string;
  /** The part that is never cut: the file name, or the path when it fits. */
  tail: string;
}

export function splitPathTail(value: string, budget = PATH_BUDGET): PathLabel {
  if (value.length <= budget) return { head: "", tail: value };

  const slash = Math.max(value.lastIndexOf("/"), value.lastIndexOf("\\"));
  const sep = slash === -1 ? "/" : value[slash];
  const name = slash === -1 ? "" : value.slice(slash + 1);
  if (!name || name.length >= budget - 1) {
    return { head: "", tail: `…${value.slice(-(budget - 1))}` };
  }

  // Three chars: leading ellipsis, separator, trailing separator.
  let room = budget - name.length - 3;
  const segments = value
    .slice(0, slash)
    .split(/[\\/]/)
    .filter(Boolean);
  const kept: string[] = [];
  for (let i = segments.length - 1; i >= 0 && room > 0; i--) {
    const cost = segments[i].length + 1;
    if (cost > room) break;
    kept.unshift(segments[i]);
    room -= cost;
  }

  const dir = kept.join(sep);
  return { head: dir ? `…${sep}${dir}${sep}` : `…${sep}`, tail: name };
}
