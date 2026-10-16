// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji

// Electron-main bridge that exposes the live ElectronMainApplication to the
// plain-CJS entry wrapper (apps/desktop/electron-entry.js).
//
// Why this exists: Theia forks its node BACKEND exactly once, inside
// `ElectronMainApplication.start()`, on an ephemeral port, and records the
// resolved port in a `Deferred` (`backendPort`) that is never re-resolved.
// Nothing watches that child afterwards. If it dies, the renderer flips to
// "Offline - Cannot connect to backend." and Theia has no way back: its built-in
// `restart()` re-creates the WINDOW but re-reads the SAME (now dead) port, so it
// cannot revive the server. The only object holding what is needed to fork a
// replacement (globals, argv, the electron security token) is the live
// ElectronMainApplication — and that instance is created inside the webpack
// bundle, so the entry wrapper cannot reach it directly.
//
// Theia calls `onStart(application)` on every ElectronMainApplicationContribution.
// We use it to publish that instance on `globalThis`; the entry wrapper's backend
// watchdog then calls `application.startBackend()` to fork a fresh backend and
// re-points the windows at the new port — reviving the backend IN PLACE, with no
// app relaunch and no quit. Registered only inside a packaged app (see
// brain-teardown.ts, the package's single `electronMain` module).

import { injectable } from '@theia/core/shared/inversify';
import {
  ElectronMainApplication,
  ElectronMainApplicationContribution,
} from '@theia/core/lib/electron-main/electron-main-application';

/**
 * Well-known `globalThis` key holding the live ElectronMainApplication. Read by
 * `apps/desktop/electron-entry.js` (`restartBackendInPlace`). Keep the two in sync.
 */
export const MAIN_APP_GLOBAL = '__undisclosed_main_app__';

@injectable()
export class MainAppBridgeContribution
  implements ElectronMainApplicationContribution {
  onStart(application: ElectronMainApplication): void {
    (globalThis as Record<string, unknown>)[MAIN_APP_GLOBAL] = application;
  }
}
