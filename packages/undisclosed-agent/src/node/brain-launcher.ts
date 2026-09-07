// Copyright (c) 2026 Simon Ugorji

import { injectable } from '@theia/core/shared/inversify';
import { BackendApplicationContribution } from '@theia/core/lib/node';
import { ChildProcess, spawn } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

/**
 * Launches + supervises the Python "brain" sidecar in a PACKAGED desktop app.
 *
 * In development the brain runs separately (`scripts/brain.sh`), so this is a
 * no-op unless the frozen `undisclosed-brain` binary is found — which only
 * happens inside the packaged Electron app, where electron-builder places it
 * under `resources/brain/`. That guard means it never double-launches against a
 * dev brain.
 *
 * Lifecycle model: the brain is spawned as the LEADER of its OWN PROCESS GROUP
 * (`detached: true` on POSIX families). That isolates it from Electron's group
 * AND means every worker / subprocess it ever spawns (uvicorn workers, python
 * tooling, shells) lands in a group we fully own. onStop() then tears the whole
 * group down — SIGTERM the negative PID, give a finite synchronous grace, and
 * SIGKILL any straggler. A hung mid-task worker cannot survive as a zombie
 * holding :5001.
 */
@injectable()
export class BrainLauncher implements BackendApplicationContribution {
  private proc: ChildProcess | undefined;

  /** macOS/Linux support negative-PID (process-group) signalling; Windows does not. */
  private static posixGroups(): boolean {
    return process.platform !== 'win32';
  }

  /** Id to signal: the negative pid (the whole group) on POSIX, the plain pid on Windows. */
  private static groupOfChild(pid: number): number {
    return BrainLauncher.posixGroups() ? -pid : pid;
  }

  onStart(): void {
    const bin = this.resolveBinary();
    if (!bin) {
      // eslint-disable-next-line no-console
      console.log(
        '[brain-launcher] no frozen brain binary found — skipping ' +
          '(dev uses scripts/brain.sh)'
      );
      return;
    }
    const port = process.env.UNDISCLOSED_BRAIN_PORT || '5001';
    // eslint-disable-next-line no-console
    console.log(`[brain-launcher] starting brain: ${bin} on :${port}`);

    const proc = spawn(bin, [], {
      env: { ...process.env, UNDISCLOSED_BRAIN_PORT: port },
      stdio: 'inherit',
      // detached: true makes the child the leader of a brand-new process group,
      // isolating it (and everything it spawns) from Electron's group so we can
      // signal it as one unit. We never unref(): the launcher owns the child for
      // the whole lifetime of the app.
      detached: BrainLauncher.posixGroups(),
    });
    this.proc = proc;

    proc.on('error', (err) => {
      // eslint-disable-next-line no-console
      console.error(`[brain-launcher] failed to start brain: ${err.message}`);
      this.proc = undefined;
    });
    proc.on('exit', (code, signal) => {
      // eslint-disable-next-line no-console
      console.error(
        `[brain-launcher] brain exited (code=${code}, signal=${signal})`
      );
      this.proc = undefined;
    });
  }

  /**
   * True while we still own a live child. Used by callers who want to know
   * whether onStop() already ran (or the brain already died on its own). The
   * Electron main process cannot reach this object directly (the brain runs in
   * the forked backend), so owning-code uses it purely for diagnostics.
   */
  stillRunning(): boolean {
    return !!this.proc && this.proc.exitCode === null && !!this.proc.pid;
  }

  /**
   * Tear the brain down, synchronously, so it is guaranteed dead before this
   * returns. Theia's BackendApplication calls onStop inside the backend's
   * `process.on('exit')` handler; async timers never run there because node tees
   * up process termination right after, so the escalation has to happen inline:
   *
   *   1. SIGTERM the whole process group (negative pid) for graceful shutdown —
   *      the brain itself force-exits after ~5s even if a task is mid-flight.
   *   2. Synchronously wait up to BRAIN_GRACE_MS for the group to reap.
   *   3. If it is still alive, SIGKILL the group so nothing can survive holding
   *      :5001, then wait again for the child handle to report exit.
   */
  onStop(): void {
    const proc = this.proc;
    if (!proc || proc.exitCode !== null || !proc.pid) {
      return;
    }
    // eslint-disable-next-line no-console
    console.log('[brain-launcher] stopping brain (process group)');

    const procId = proc.pid;
    const group = BrainLauncher.groupOfChild(procId);
    const graceMs = Number(process.env.UNDISCLOSED_BRAIN_STOP_GRACE_MS || 1600);
    const log = (msg: string) =>
      // eslint-disable-next-line no-console
      console.log(`[brain-launcher] ${msg}`);

    const signalGroup = (sig: NodeJS.Signals): boolean => {
      try {
        process.kill(group, sig);
        return true;
      } catch (err) {
        const e = err as NodeJS.ErrnoException;
        if (e.code === 'ESRCH') {
          return false; // group already gone
        }
        if (e.code === 'EPERM') {
          // Not our group (rare) — fall back to the direct child.
          log(`group ${sig} denied, signalling child`);
          try {
            proc.kill(sig);
          } catch {
            return false;
          }
        } else {
          log(`${sig} failed: ${e.message}`);
        }
        return true;
      }
    };

    const hasExited = (): boolean =>
      proc.exitCode !== null || proc.signalCode !== null;

    // Blocking sleep that works inside an 'exit' handler (no event loop needed).
    const sleep = (ms: number): void => {
      const sab = new SharedArrayBuffer(4);
      Atomics.wait(new Int32Array(sab), 0, 0, ms);
    };

    if (!signalGroup('SIGTERM')) {
      log('brain group already gone at stop');
      return;
    }

    // Wait out the grace window, checking for exit as we go.
    const pollInterval = 40;
    let waited = 0;
    while (!hasExited() && waited < graceMs) {
      sleep(Math.min(pollInterval, graceMs - waited));
      waited += pollInterval;
    }

    if (!hasExited()) {
      log('grace elapsed, sending SIGKILL to process group');
      if (signalGroup('SIGKILL')) {
        // Give the SIGKILL a moment to land and reap before we return.
        waited = 0;
        while (!hasExited() && waited < 1000) {
          sleep(40);
          waited += 40;
        }
      }
    }
    // The 'exit' listener clears this.proc; if somehow still set, forget it so a
    // stale handle can't confuse a later stillRunning() check.
    if (this.proc === proc && hasExited()) {
      this.proc = undefined;
    }
    log(hasExited() ? 'brain stopped cleanly' : 'brain may be orphaned');
  }

  private resolveBinary(): string | undefined {
    const name =
      process.platform === 'win32'
        ? 'undisclosed-brain.exe'
        : 'undisclosed-brain';
    const resourcesPath = (
      process as NodeJS.Process & { resourcesPath?: string }
    ).resourcesPath;
    const candidates = [
      process.env.UNDISCLOSED_BRAIN_BIN,
      // electron-builder extraResources -> <resources>/brain/undisclosed-brain
      resourcesPath ? path.join(resourcesPath, 'brain', name) : undefined,
    ].filter(Boolean) as string[];
    return candidates.find((c) => fs.existsSync(c));
  }
}
