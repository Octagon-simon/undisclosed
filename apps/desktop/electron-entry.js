// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Simon Ugorji
//
// Electron main ENTRY WRAPPER (package.json "main").
//
// Theia's plugin deployer only deploys LOCAL plugins named in
// THEIA_DEFAULT_PLUGINS / THEIA_PLUGINS / --plugins (see plugin-deployer-impl.js:
// there is NO relative-"plugins"-dir fallback). In dev, `theia start` arranges
// this; a packaged Electron app does NOT. We bundle the VS Code builtin language
// servers under <app>/plugins (electron-builder `files`), so without this the
// shipped app has zero language intelligence — Cmd+Click / go-to-definition /
// references / hover all silently do nothing even though the plugins are present.
//
// Point the deployer at the bundled dir BEFORE requiring the generated main (so
// the deployer, which runs early in the forked backend, inherits it). Set only
// if unset, so an explicit override still wins.
const path = require('path');

if (!process.env.THEIA_DEFAULT_PLUGINS) {
  // This file sits at the app root (Resources/app) in the packaged app, next to
  // the bundled `plugins/` dir (matches THEIA_APP_PROJECT_PATH the generated
  // main derives as resolve(lib/backend, '..', '..')).
  const pluginsDir = path.resolve(__dirname, 'plugins');
  process.env.THEIA_DEFAULT_PLUGINS = `local-dir:${pluginsDir}`;
}

// --- Sleep/wake & crash recovery -------------------------------------------
// On macOS, sleeping the machine and resuming can kill the renderer process or
// drop its GPU/compositor context. Chromium then shows a BLANK window with no
// built-in recovery, so the app looks dead until a manual restart. Theia's
// generated main installs no handler for this. We reload the renderer in place
// when it dies — this keeps the backend AND the brain sidecar alive, so it is
// faster and less disruptive than the full app restart it currently takes.
//
// Registered BEFORE requiring the Theia main so the `web-contents-created` hook
// is in place before any window is created. Best-effort: never block startup.
try {
  const electron = require('electron');
  const { app } = electron;

  // render-process-gone reasons that mean the renderer is actually dead (vs a
  // normal `clean-exit` on quit, which must NOT trigger a reload).
  const RELOAD_REASONS = new Set([
    'crashed',
    'abnormal-exit',
    'oom',
    'killed',
    'launch-failed',
    'integrity-failure',
  ]);

  // Debounce so a genuine crash-loop can't hammer reload() forever.
  const lastReload = new WeakMap();
  const reloadOnce = (wc, why) => {
    if (!wc || wc.isDestroyed()) {
      return;
    }
    const now = Date.now();
    if (now - (lastReload.get(wc) || 0) < 5000) {
      return; // reloaded very recently — let it settle instead of looping
    }
    lastReload.set(wc, now);
    // eslint-disable-next-line no-console
    console.warn(`[undisclosed] renderer recovery: reloading after ${why}`);
    try {
      wc.reload();
    } catch (_e) {
      /* ignore — nothing more we can do here */
    }
  };

  app.on('web-contents-created', (_event, wc) => {
    wc.on('render-process-gone', (_e, details) => {
      const reason = details && details.reason;
      if (RELOAD_REASONS.has(reason)) {
        reloadOnce(wc, `render-process-gone (${reason})`);
      }
    });
  });

  // A GPU-process crash can blank the window while the renderer survives, so
  // render-process-gone never fires — reload every window to re-establish the
  // compositor.
  app.on('child-process-gone', (_event, details) => {
    if (details && details.type === 'GPU') {
      for (const win of electron.BrowserWindow.getAllWindows()) {
        reloadOnce(win.webContents, 'GPU process gone');
      }
    }
  });
} catch (_e) {
  /* recovery wiring is best-effort; never prevent the app from starting */
}

require('./lib/backend/electron-main.js');
