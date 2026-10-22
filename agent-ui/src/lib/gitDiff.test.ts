// Copyright (c) 2026 Simon Ugorji
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchFileChange, statusFromPatch } from '@/lib/gitDiff';

type Handler = (args: string[]) => string;

function mockGit(handler: Handler) {
  vi.stubGlobal('window', {
    __UNDISCLOSED_BACKEND_ORIGIN__: 'http://localhost:3000',
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init: { body?: string }) => {
      const { args } = JSON.parse(init.body ?? '{}') as { args: string[] };
      return {
        ok: true,
        json: async () => ({ stdout: handler(args), stderr: '', exitCode: 0 }),
      };
    })
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const MODIFIED_ONLY_DELETIONS = [
  'diff --git a/src/a.ts b/src/a.ts',
  'index 111..222 100644',
  '--- a/src/a.ts',
  '+++ b/src/a.ts',
  '@@ -1,2 +1 @@',
  '-old line',
  ' kept line',
].join('\n');

const DELETED = [
  'diff --git a/src/gone.ts b/src/gone.ts',
  'deleted file mode 100644',
  '--- a/src/gone.ts',
  '+++ /dev/null',
  '@@ -1 +0,0 @@',
  '-gone',
].join('\n');

const NEW_FILE = [
  'diff --git a/src/new.ts b/src/new.ts',
  'new file mode 100644',
  '--- /dev/null',
  '+++ b/src/new.ts',
  '@@ -0,0 +1,2 @@',
  '+first',
  '+second',
].join('\n');

describe('fetchFileChange', () => {
  it('keeps M for a modification that only deletes lines', async () => {
    mockGit((args) => {
      if (args[0] === 'status') return ' M src/a.ts\n';
      if (args[0] === 'diff' && args[1] === 'HEAD')
        return MODIFIED_ONLY_DELETIONS;
      return '';
    });

    const change = await fetchFileChange('/repo/src/a.ts', '/repo');
    expect(change?.status).toBe('M');
    expect(change?.patch).toContain('-old line');
  });

  it('reports D only when git says the file was deleted', async () => {
    mockGit((args) => {
      if (args[0] === 'status') return ' D src/gone.ts\n';
      if (args[0] === 'diff' && args[1] === 'HEAD') return DELETED;
      return '';
    });

    const change = await fetchFileChange('/repo/src/gone.ts', '/repo');
    expect(change?.status).toBe('D');
  });

  it('marks an untracked file A and diffs it against /dev/null', async () => {
    mockGit((args) => {
      if (args[0] === 'status') return '?? src/new.ts\n';
      if (args[0] === 'diff' && args.includes('--no-index')) return NEW_FILE;
      return '';
    });

    const change = await fetchFileChange('/repo/src/new.ts', '/repo');
    expect(change?.status).toBe('A');
    expect(change?.patch).toContain('+first');
  });

  it('falls back to the last commit when the turn already committed', async () => {
    mockGit((args) => {
      if (args[0] === 'status') return '';
      if (args[0] === 'rev-parse') return 'abc123\n';
      if (args[0] === 'log') return 'abc123\n';
      if (args[0] === 'diff' && args[1] === 'HEAD^') return NEW_FILE;
      return '';
    });

    const change = await fetchFileChange('/repo/src/new.ts', '/repo');
    expect(change?.patch).toContain('+second');
    expect(change?.status).toBe('A');
  });

  it('does not borrow an older commit that did not touch the file', async () => {
    mockGit((args) => {
      if (args[0] === 'status') return '';
      if (args[0] === 'rev-parse') return 'head-sha\n';
      if (args[0] === 'log') return 'older-sha\n';
      if (args[0] === 'diff' && args[1] === 'HEAD^') return NEW_FILE;
      return '';
    });

    const change = await fetchFileChange('/repo/src/new.ts', '/repo');
    expect(change?.patch).toBe('');
    expect(change?.status).toBeNull();
  });
});

describe('statusFromPatch', () => {
  it('reads new and deleted markers, and leaves a plain edit alone', () => {
    expect(statusFromPatch(NEW_FILE)).toBe('A');
    expect(statusFromPatch(DELETED)).toBe('D');
    expect(statusFromPatch(MODIFIED_ONLY_DELETIONS)).toBeNull();
  });
});
