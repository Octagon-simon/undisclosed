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
 * Embedded code editor pane, gated behind the `codeEditorEnabled` flag.
 *
 * Lifecycle the user sees:
 *   1. First time only — an explicit "Install" step downloads the editor
 *      (code-server) with a progress bar. We never silently pull a few hundred
 *      MB when the user just opens a folder.
 *   2. "Open Folder" (VS Code style) or the project's bound folder.
 *   3. The main process spawns a local editor server for that folder and we
 *      load it in an iframe.
 */

import { Button } from '@/components/ui/button';
import { useHost } from '@/host';
import { useAuthStore } from '@/store/authStore';
import { useSpaceStore } from '@/store/spaceStore';
import { AlertTriangle, Download, Loader2 } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

type Phase =
  | 'checking'
  | 'needs-install'
  | 'installing'
  | 'no-folder'
  | 'starting'
  | 'ready'
  | 'error'
  | 'disabled';

export default function CodeAgentWorkspace({
  active = true,
}: {
  /** Whether the editor pane is currently visible. The server is spawned only
   *  after the first time it becomes active (lazy), then stays running so the
   *  iframe persists across navigation. */
  active?: boolean;
} = {}) {
  const host = useHost();
  const codeEditorEnabled = useAuthStore((s) => s.codeEditorEnabled);
  const codeEditorLastFolder = useAuthStore((s) => s.codeEditorLastFolder);
  const setCodeEditorLastFolder = useAuthStore(
    (s) => s.setCodeEditorLastFolder
  );
  // Decision A: a space owns the folder. The editor opens the active space's
  // bound local folder (`rootPath`), so Code/Workspace/agent are all bound to
  // one workspace. A `chosenFolder` (ad-hoc "Open Folder") overrides it.
  const workdir = useSpaceStore((s) =>
    s.activeSpaceId ? (s.spaces[s.activeSpaceId]?.rootPath ?? null) : null
  );

  const [phase, setPhase] = useState<Phase>('checking');
  const [provisioned, setProvisioned] = useState<boolean | null>(null);
  const [progress, setProgress] = useState(0);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [chosenFolder, setChosenFolder] = useState<string | null>(
    codeEditorLastFolder
  );
  const startedFor = useRef('');

  const effectiveWorkdir = chosenFolder ?? workdir ?? null;

  // 1. Is the editor installed?
  useEffect(() => {
    if (!codeEditorEnabled) {
      setPhase('disabled');
      return;
    }
    let cancelled = false;
    setPhase('checking');
    void host?.electronAPI
      ?.codeEditorProvisioned?.()
      .then((p: boolean) => !cancelled && setProvisioned(!!p))
      .catch(() => !cancelled && setProvisioned(false));
    return () => {
      cancelled = true;
    };
  }, [codeEditorEnabled, host]);

  const start = useCallback(async () => {
    if (!effectiveWorkdir) {
      setPhase('no-folder');
      return;
    }
    // The editor server is per-folder, so key instances by the folder itself.
    const instanceKey = effectiveWorkdir;
    if (
      startedFor.current === instanceKey &&
      (phase === 'ready' || phase === 'starting')
    ) {
      return;
    }
    startedFor.current = instanceKey;
    setPhase('starting');
    setError('');
    try {
      const res = await host?.electronAPI?.codeEditorStart?.(
        instanceKey,
        effectiveWorkdir
      );
      if (res?.notProvisioned) {
        setProvisioned(false);
        return;
      }
      if (res?.success && res.url) {
        setUrl(res.url);
        setPhase('ready');
      } else {
        setError(res?.error || 'Failed to start the editor.');
        setPhase('error');
      }
    } catch (e: any) {
      setError(e?.message || String(e));
      setPhase('error');
    }
  }, [effectiveWorkdir, host, phase]);

  // 2. Once install state + folder are known, route to the right phase.
  useEffect(() => {
    if (!codeEditorEnabled || provisioned === null) return;
    if (!provisioned) {
      setPhase('needs-install');
      return;
    }
    if (!effectiveWorkdir) {
      setPhase('no-folder');
      return;
    }
    // Lazy: don't spawn the editor server until the pane is first shown. Once
    // started it stays running (the component stays mounted), so this guard
    // only delays the initial spawn.
    if (!active) return;
    void start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provisioned, effectiveWorkdir, codeEditorEnabled, active]);

  const install = useCallback(async () => {
    setPhase('installing');
    setProgress(0);
    setError('');
    const off = host?.electronAPI?.onCodeEditorProgress?.(
      (p: { received: number; total: number; percent: number }) =>
        setProgress(p.percent)
    );
    try {
      const res = await host?.electronAPI?.codeEditorProvision?.();
      if (res?.success) {
        setProvisioned(true); // routes via the effect above
      } else {
        setError(res?.error || 'Failed to install the editor.');
        setPhase('error');
      }
    } catch (e: any) {
      setError(e?.message || String(e));
      setPhase('error');
    } finally {
      off?.();
    }
  }, [host]);

  const openFolder = useCallback(async () => {
    try {
      const res = await host?.electronAPI?.selectFile?.({
        properties: ['openDirectory'],
      });
      const picked = res?.files?.[0]?.filePath;
      if (picked) {
        startedFor.current = '';
        // Optimistic local override so the editor starts immediately.
        setChosenFolder(picked);
        setCodeEditorLastFolder(picked);
        // Decision A: bind the folder to the active space so it persists as the
        // space's rootPath (Code/Workspace/agent all share this one folder).
        // Best-effort — on failure the local override above still works.
        const { activeSpaceId, relocateSpaceOnServer } =
          useSpaceStore.getState();
        if (activeSpaceId) {
          void relocateSpaceOnServer(activeSpaceId, picked).catch((e) => {
            console.warn('Failed to bind folder to active space:', e);
          });
        }
      }
    } catch (e) {
      console.error('Open folder failed:', e);
    }
  }, [host, setCodeEditorLastFolder]);

  if (phase === 'disabled') {
    return (
      <Centered>
        The code editor is turned off. Enable it in Settings to use it.
      </Centered>
    );
  }

  if (phase === 'checking') {
    return (
      <Centered>
        <Spinner label="Loading…" />
      </Centered>
    );
  }

  if (phase === 'needs-install') {
    return (
      <Centered>
        <div className="flex max-w-[520px] flex-col items-center gap-3 text-center">
          <div className="text-body-sm font-semibold text-ds-text-neutral-default-default">
            Set up the code editor
          </div>
          <div className="text-label-xs text-ds-text-neutral-subtle-default">
            A one-time download (~200 MB). It runs entirely on your machine —
            nothing is sent anywhere.
          </div>
          <Button
            type="button"
            variant="primary"
            size="sm"
            buttonContent="text"
            onClick={() => void install()}
            className="mt-1 gap-1.5"
          >
            <Download className="h-4 w-4" aria-hidden />
            Install editor
          </Button>
        </div>
      </Centered>
    );
  }

  if (phase === 'installing') {
    return (
      <Centered>
        <div className="flex w-[320px] max-w-[80vw] flex-col items-center gap-3 text-center">
          <div className="text-body-sm font-semibold text-ds-text-neutral-default-default">
            Downloading the editor…
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-ds-bg-neutral-muted-default">
            <div
              className="h-full rounded-full bg-ds-bg-brand-default-default transition-[width] duration-200"
              style={{ width: `${progress}%` }}
            />
          </div>
          <div className="text-label-xs text-ds-text-neutral-subtle-default">
            {progress}% — one-time setup
          </div>
        </div>
      </Centered>
    );
  }

  if (phase === 'no-folder') {
    return (
      <Centered>
        <div className="flex max-w-[520px] flex-col items-center gap-3 text-center">
          <div className="text-body-sm text-ds-text-neutral-subtle-default">
            Open a folder to start editing — everything runs locally on your
            machine.
          </div>
          <button
            type="button"
            onClick={() => void openFolder()}
            className="rounded-lg border border-solid border-ds-border-neutral-default-default px-3 py-1.5 text-label-sm font-semibold text-ds-text-neutral-default-default hover:bg-ds-bg-neutral-subtle-default"
          >
            Open Folder…
          </button>
        </div>
      </Centered>
    );
  }

  if (phase === 'error') {
    return (
      <Centered>
        <div className="flex max-w-[520px] flex-col items-center gap-2 text-center">
          <AlertTriangle className="h-5 w-5 text-ds-icon-error-default-default" />
          <div className="text-body-sm font-semibold text-ds-text-error-strong-default">
            Something went wrong
          </div>
          <div className="text-label-xs text-ds-text-neutral-subtle-default">
            {error}
          </div>
          <button
            type="button"
            onClick={() => {
              startedFor.current = '';
              setError('');
              // Re-check install state, then route.
              setPhase('checking');
              void host?.electronAPI
                ?.codeEditorProvisioned?.()
                .then((p: boolean) => setProvisioned(!!p))
                .catch(() => setProvisioned(false));
            }}
            className="mt-1 rounded-lg border border-solid border-ds-border-neutral-default-default px-3 py-1 text-label-xs font-semibold text-ds-text-neutral-default-default hover:bg-ds-bg-neutral-subtle-default"
          >
            Retry
          </button>
        </div>
      </Centered>
    );
  }

  if (phase !== 'ready' || !url) {
    return (
      <Centered>
        <Spinner label="Starting the editor…" />
      </Centered>
    );
  }

  return (
    <div className="flex h-full w-full flex-col overflow-hidden rounded-xl bg-ds-bg-neutral-default-default">
      <iframe
        title="Code editor"
        src={url}
        className="h-full w-full border-0"
        allow="clipboard-read; clipboard-write"
      />
    </div>
  );
}

function Spinner({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 text-ds-text-neutral-subtle-default">
      <Loader2 className="h-4 w-4 animate-spin" />
      <span className="text-body-sm">{label}</span>
    </div>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full w-full items-center justify-center p-6">
      <div className="text-center text-body-sm text-ds-text-neutral-subtle-default">
        {children}
      </div>
    </div>
  );
}
