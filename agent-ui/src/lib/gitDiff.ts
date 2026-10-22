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

/**
 * Git's own single-letter state for a changed file. `R` (rename) is reported as
 * `M` because the badge only distinguishes added / modified / deleted.
 */
export type FileChangeStatus = 'M' | 'A' | 'D';

export interface FileChange {
  /** Unified patch, or `''` when git reports no difference for the path. */
  patch: string;
  /** Status from `git status`, or inferred from the patch when the tree is clean. */
  status: FileChangeStatus | null;
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

/** Porcelain `XY` codes -> the badge letter. */
function statusFromPorcelain(stdout: string): FileChangeStatus | null {
  const code = (stdout.split('\n').find((line) => line.trim()) ?? '').slice(
    0,
    2
  );
  if (!code.trim()) return null;
  if (code === '??' || code.includes('A')) return 'A';
  if (code.includes('D')) return 'D';
  return 'M';
}

/**
 * A delete/new patch carries the fact the worktree status cannot once the turn
 * has committed: `git status` is clean, but the patch still names the mode.
 */
export function statusFromPatch(patch: string): FileChangeStatus | null {
  if (
    /^deleted file mode /m.test(patch) ||
    /^\+\+\+ \/dev\/null$/m.test(patch)
  ) {
    return 'D';
  }
  if (/^new file mode /m.test(patch) || /^--- \/dev\/null$/m.test(patch)) {
    return 'A';
  }
  return null;
}

async function patchText(
  cwd: string,
  rel: string,
  untracked: boolean
): Promise<string> {
  const diff = async (args: string[]) =>
    (await gitExec(args, cwd))?.stdout ?? '';

  if (untracked) {
    return diff([
      'diff',
      '--no-index',
      '--no-color',
      '--',
      '/dev/null',
      rel,
    ]);
  }

  // HEAD covers staged + unstaged in one patch. --cached covers a repo with no
  // HEAD yet (all files staged as new); the plain diff covers unstaged-only.
  for (const args of [
    ['diff', 'HEAD', '--no-color', '--', rel],
    ['diff', '--cached', '--no-color', '--', rel],
    ['diff', '--no-color', '--', rel],
  ]) {
    const out = await diff(args);
    if (out.trim()) return out;
  }
  return '';
}

/**
 * The turn may already have committed its work, leaving the worktree clean and
 * `git diff HEAD` empty. When HEAD is the commit that last touched the file,
 * diff that commit instead so the card still shows what changed.
 */
async function lastCommitPatch(cwd: string, rel: string): Promise<string> {
  const [head, touched] = await Promise.all([
    gitExec(['rev-parse', 'HEAD'], cwd),
    gitExec(['log', '-1', '--format=%H', '--', rel], cwd),
  ]);
  const headSha = (head?.stdout ?? '').trim();
  if (!headSha || (touched?.stdout ?? '').trim() !== headSha) return '';
  return (await gitExec(['diff', 'HEAD^', 'HEAD', '--no-color', '--', rel], cwd))
    ?.stdout ?? '';
}

/**
 * The patch and status for one changed file.
 *
 * Untracked (brand-new) files are diffed against `/dev/null` so all their lines
 * show as additions. Status comes from `git status`, never from the add/remove
 * counts: a modified file whose change was pure deletion has `+0 -N` and is
 * still `M`, while only a file git reports as deleted gets `D`.
 */
export async function fetchFileChange(
  filePath: string,
  root?: string
): Promise<FileChange | null> {
  const cwd = root ?? getOpenFolderRoot();
  if (!cwd || !backendOrigin()) return null;
  const rel = toRepoRelative(filePath, cwd);
  if (!rel) return null;

  const statusOut = await gitExec(
    ['status', '--porcelain', '--', rel],
    cwd
  );
  if (statusOut == null) return null;

  const porcelain = statusOut.stdout ?? '';
  const untracked = porcelain
    .split('\n')
    .some((line) => line.startsWith('??'));
  let patch = await patchText(cwd, rel, untracked);
  if (!patch.trim() && !untracked) patch = await lastCommitPatch(cwd, rel);

  return {
    patch,
    status: statusFromPorcelain(porcelain) ?? statusFromPatch(patch),
  };
}
