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
 */
@injectable()
export class BrainLauncher implements BackendApplicationContribution {
  private proc: ChildProcess | undefined;

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
    this.proc = spawn(bin, [], {
      env: { ...process.env, UNDISCLOSED_BRAIN_PORT: port },
      stdio: 'inherit',
    });
    this.proc.on('exit', (code) => {
      // eslint-disable-next-line no-console
      console.error(`[brain-launcher] brain exited with code ${code}`);
      this.proc = undefined;
    });
  }

  onStop(): void {
    if (this.proc) {
      // eslint-disable-next-line no-console
      console.log('[brain-launcher] stopping brain');
      this.proc.kill();
      this.proc = undefined;
    }
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
