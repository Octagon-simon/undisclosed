// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

// Electron-main-process contribution for the Undisclosed desktop app.
//
// Background: the frozen brain runs as a detached, group-leading child of the
// forked BACKEND Node process (see ../node/brain-launcher.ts). On a NORMAL quit
// Theia tears the backend down: Electron main `app.on('quit')` ->
// `process.kill(backendPid)` -> the backend's `process.on('exit')` ->
// BackendApplication.onStop() -> contribution onStop(). Two holes can still leak
// the brain so it keeps holding :5001:
//
//   1. Theia kills just the backend PID, relying on it to reap its own children.
//      A task hung mid-flight can make the backend's own stop SIGKILL its group
//      yet leave the detached sidecar (re-parented under `init`) alive.
//   2. A force-quit / crash / SIGKILL never runs the backend exit path at all.
//
// Electron ALWAYS emits `will-quit` on its MAIN process just before dying
// (normal close AND Cmd+Q, synchronous, once per process). So this file binds an
// ElectronMainApplicationContribution whose onStop() — invoked by Theia on that
// event, after the graceful backend teardown had its chance — sweeps the brain
// port. In node/brain-launcher.ts the frozen brain is spawned `detached` and is
// therefore the leader of its OWN process group (it keeps that group id even
// once it re-parents under `init`). So the sweep only has to find the listener
// pid and `kill(-pid)` (the negative pid = the whole group). That closes both
// leak paths regardless of how the user quits.

import { injectable } from '@theia/core/shared/inversify';
import { ContainerModule } from '@theia/core/shared/inversify';
import {
  ElectronMainApplication,
  ElectronMainApplicationContribution,
} from '@theia/core/lib/electron-main/electron-main-application';
import * as cp from 'child_process';

/**
 * Resolve the process-group id of `pid`, or `undefined` on error. On POSIX a
 * `detached` process keeps its own pgid even after it re-parents, so this is
 * how we find the group BrainLauncher created.
 */
function groupIdOf(pid: number | string): number | undefined {
  try {
    const out = cp
      .spawnSync('ps', ['-o', 'pgid=', '-p', String(pid)], {
        encoding: 'utf8',
      })
      .stdout.trim();
    const pg = Number.parseInt(out, 10);
    return Number.isFinite(pg) ? pg : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Kill every process still bound to the brain port, whole-group, synchronously.
 *
 * Runs from Electron's `will-quit` on the MAIN (not forked) process. `lsof -ti`
 * prints each listener's pid; for each we resolve its process-group id and
 * SIGKILL the whole group with `kill(-pgid)`. Killing the group (not the bare
 * pid) is what catches a uvicorn server plus the python tooling and shells a
 * stuck task may have spawned. Everything is best-effort — a failed sweep must
 * never throw during `will-quit`.
 */
export function sweepBrainPort(port: number): void {
  if (process.platform === 'win32') {
    // Windows: no POSIX process groups. Fall back to taskkill /T (tree) per
    // listener reported by netstat.
    try {
      const lines = cp
        .spawnSync('netstat', ['-ano'], { encoding: 'utf8' })
        .stdout.split('\n');
      const re = new RegExp(`:${port}\\b.*LISTENING\\s+(\\d+)\\s*$`, 'i');
      const pids = new Set<string>();
      for (const line of lines) {
        const m = line.match(re);
        if (m) {
          pids.add(m[1]);
        }
      }
      for (const pid of pids) {
        cp.spawnSync('taskkill', ['/F', '/T', '/PID', pid], {
          encoding: 'utf8',
        });
      }
    } catch {
      /* ignore */
    }
    return;
  }

  // Enumerate every pid currently holding the port.
  let holders = '';
  try {
    holders = cp
      .spawnSync('lsof', ['-ti', `:${port}`], { encoding: 'utf8' })
      .stdout.trim();
  } catch {
    return;
  }
  for (const pid of holders.split(/\s+/).filter((p) => p.length)) {
    // This process must never kill itself (defensive; lsof could list us if the
    // Electron dev server itself bound the port, which it doesn't).
    if (Number(pid) === process.pid) {
      continue;
    }
    const pg = groupIdOf(pid) ?? Number(pid);
    try {
      // Kill the WHOLE group (negative pid). If the group can't be signalled,
      // fall back to the single holder.
      if (pg !== Number(pid)) {
        try {
          process.kill(-pg, 'SIGKILL');
        } catch {
          process.kill(Number(pid), 'SIGKILL');
        }
      } else {
        process.kill(Number(pid), 'SIGKILL');
      }
    } catch {
      /* ESRCH — already gone; ignore */
    }
  }
}

function resourcesPresent(): boolean {
  return !!(process as NodeJS.Process & { resourcesPath?: string })
    .resourcesPath;
}

const BRAIN_PORT = Number(process.env.UNDISCLOSED_BRAIN_PORT || 5001);

/**
 * Bound to the will-quit sweep. Registered only when we're inside a packaged app
 * (Electron sets process.resourcesPath on the main process) so dev builds stay
 * untouched.
 */
@injectable()
export class BrainTeardownContribution
  implements ElectronMainApplicationContribution {
  onStop(_application: ElectronMainApplication): void {
    sweepBrainPort(BRAIN_PORT);
  }
}

export default new ContainerModule((bind) => {
  if (resourcesPresent()) {
    bind(ElectronMainApplicationContribution)
      .to(BrainTeardownContribution)
      .inSingletonScope();
  }
});
