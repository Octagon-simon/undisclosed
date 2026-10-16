// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

/**
 * Unified-diff source for the Changed Files card (Phase 3b of
 * `agent-panel-integration-plan.md`).
 *
 * The diff is read from the Theia backend's git endpoint
 * (`POST /undisclosed-agent/git/exec`, see `git-extras-contribution.ts` and the
 * node backend module). That endpoint already existed for the Source Control
 * extras (Undo Last Commit, AI commit message) and runs a whitelisted `git`
 * subcommand in a working dir — so the panel reuses it instead of a new
 * stream. The backend origin is stashed on `window` by `mount.tsx`
 * (`__UNDISCLOSED_BACKEND_ORIGIN__`); it MUST be absolute because the packaged
 * app runs the panel from a `file://` page.
 *
 * Returns `null` (not an error) whenever the host can't provide a diff — the
 * standalone web host has no backend origin, and a folder that isn't a git repo
 * has no workspace root — so callers render the card without diff rows.
 */

import { getOpenFolderRoot } from './openFolder';

interface GitExecResult {
  stdout?: string;
  stderr?: string;
  exitCode?: number;
}

/** The Theia backend origin, or null when it isn't available (web host). */
function backendOrigin(): string | null {
  if (typeof window === 'undefined') return null;
  const origin = (
    window as unknown as { __UNDISCLOSED_BACKEND_ORIGIN__?: string }
  ).__UNDISCLOSED_BACKEND_ORIGIN__;
  return origin && /^https?:\/\//.test(origin)
    ? origin.replace(/\/+$/, '')
    : null;
}

/** Run one whitelisted `git` subcommand via the backend endpoint. */
async function gitExec(
  args: string[],
  cwd: string
): Promise<GitExecResult | null> {
  const origin = backendOrigin();
  if (!origin || !cwd) return null;
  try {
    const res = await fetch(`${origin}/undisclosed-agent/git/exec`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cwd, args }),
      cache: 'no-store',
    });
    if (!res.ok) return null;
    return (await res.json()) as GitExecResult;
  } catch {
    return null;
  }
}

/**
 * The panel reports changed-file paths absolute or relative to the workspace
 * root; `git` wants a repo-relative path. Strip the `file://` scheme and the
 * workspace-root prefix when either is present.
 */
function toRepoRelative(filePath: string, root: string): string {
  let p = filePath;
  if (p.startsWith('file://')) {
    try {
      p = decodeURIComponent(p.replace(/^file:\/\//, ''));
    } catch {
      p = p.replace(/^file:\/\//, '');
    }
  }
  const normRoot = root.replace(/\/+$/, '');
  if (p === normRoot) return '';
  if (p.startsWith(`${normRoot}/`)) p = p.slice(normRoot.length + 1);
  return p.replace(/^\.\//, '');
}

/**
 * The unified diff for one changed file. Untracked (brand-new) files don't
 * appear in `git diff HEAD`, so they're diffed against `/dev/null` to show all
 * their lines as additions. Returns the patch text (possibly `''` when git
 * reports no diff), or `null` when the host can't provide one at all.
 */
export async function fetchFileDiff(
  filePath: string,
  root?: string
): Promise<string | null> {
  const cwd = root ?? getOpenFolderRoot();
  if (!cwd || !backendOrigin()) return null;
  const rel = toRepoRelative(filePath, cwd);
  if (!rel) return null;

  // Untracked → diff against /dev/null so a new agent-created file still shows.
  const status = await gitExec(['status', '--porcelain', '--', rel], cwd);
  if (status == null) return null;
  const code = (status.stdout ?? '').trim().slice(0, 2);
  if (code === '??') {
    const untracked = await gitExec(
      ['diff', '--no-index', '--no-color', '--', '/dev/null', rel],
      cwd
    );
    return untracked?.stdout ?? '';
  }

  // Tracked → diff against HEAD (covers staged + unstaged in one patch); fall
  // back to the plain working-tree diff for the (rare) unstaged-only case.
  const againstHead = await gitExec(
    ['diff', 'HEAD', '--no-color', '--', rel],
    cwd
  );
  const patch = againstHead?.stdout ?? '';
  if (patch.trim()) return patch;
  const working = await gitExec(['diff', '--no-color', '--', rel], cwd);
  return working?.stdout ?? patch;
}
