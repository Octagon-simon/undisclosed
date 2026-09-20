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
  const { app, BrowserWindow } = electron;
  const http = require('http');
  const fs = require('fs');
  const os = require('os');
  const { spawnSync } = require('child_process');

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

  // --- Sleep/wake recovery for the brain + UI --------------------------------
  //
  // Sleeping the Mac and resuming breaks the app in ways the crash hooks above
  // do not cover:
  //
  //  1. Sockets HALF-OPEN. The brain keeps its LISTEN socket, so TCP still
  //     connects, but the connections the clients were already using are gone
  //     and no close frame ever arrives — the renderer's stream and the editor
  //     backend's pooled socket to the brain look alive and then hang.
  //  2. A turn that was mid-flight when the Mac slept is unrecoverable: its
  //     outbound model/MCP sockets are dead, so that turn never finishes and
  //     holds the task. /health can still answer 200 in this state, which is why
  //     a pure health probe is not enough.
  //
  // So on 'resume' we decide whether to (re)start the brain, wait for it to
  // answer, then reload every window so Theia restores layout/editors and the
  // agent panel reattaches against a clean brain. In the packaged app the
  // supervisor is the backend's BrainLauncher; in dev it is scripts/brain.sh.
  // Both respawn the brain when it exits, so killing the listener is enough.
  //
  // Opt out with UNDISCLOSED_DISABLE_RESUME_RECOVERY=1.
  const BRAIN_PORT = Number(process.env.UNDISCLOSED_BRAIN_PORT || 5001);
  // Let the OS settle after wake before we touch sockets/windows.
  const RESUME_SETTLE_MS = Number(process.env.UNDISCLOSED_RESUME_SETTLE_MS || 1500);
  // How long to wait for a restarted brain to answer before reloading the UI.
  const BRAIN_REVIVE_TIMEOUT_MS = Number(
    process.env.UNDISCLOSED_BRAIN_REVIVE_TIMEOUT_MS || 20000
  );
  const recoveryDisabled =
    process.env.UNDISCLOSED_DISABLE_RESUME_RECOVERY === '1';

  // Whether to force a fresh brain on wake even when /health still answers:
  //   auto (default): restart when the brain is unresponsive OR we were asleep
  //                   at least UNDISCLOSED_RESUME_FORCE_RESTART_SLEEP_MS.
  //   always / never: override.
  const FORCE_RESTART = (
    process.env.UNDISCLOSED_RESUME_FORCE_BRAIN_RESTART || 'auto'
  ).toLowerCase();
  const FORCE_RESTART_SLEEP_MS = Number(
    process.env.UNDISCLOSED_RESUME_FORCE_RESTART_SLEEP_MS || 60000
  );

  // Backstop watchdog. A wedged-but-listening brain never exits, so neither the
  // supervisor's exit hook nor a reload fixes it; and a broken state that no
  // power event reported has no trigger at all. This probes /health from the
  // main process and, after a SUSTAINED run of failures while something is still
  // listening, recycles the brain exactly like a wake does. The window is
  // deliberately generous: while a long blocking tool runs, /health legitimately
  // times out, so a short window would kill a busy-but-healthy brain.
  const WATCH_MS = Number(process.env.UNDISCLOSED_DESKTOP_WATCH_MS || 30000);
  const WATCH_FAILS = Number(process.env.UNDISCLOSED_DESKTOP_WATCH_FAILS || 5);

  // Recovery is logged to a file as well as the console. In a packaged app
  // console output goes to the unified log and is effectively invisible, which
  // is why a bad wake used to leave no trace to diagnose afterwards.
  const RECOVERY_LOG = path.join(
    process.env.UNDISCLOSED_DATA_DIR || path.join(os.homedir(), '.undisclosed'),
    'logs',
    'desktop-recovery.log'
  );
  const logLine = (msg) => {
    const line = `${new Date().toISOString()} [undisclosed] ${msg}`;
    // eslint-disable-next-line no-console
    console.warn(line);
    try {
      fs.mkdirSync(path.dirname(RECOVERY_LOG), { recursive: true });
      fs.appendFileSync(RECOVERY_LOG, line + '\n');
    } catch (_e) {
      /* logging is best-effort */
    }
  };

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  /** One /health probe. True only on HTTP 200. */
  const probeBrain = (timeoutMs) =>
    new Promise((resolve) => {
      let settled = false;
      const done = (ok) => {
        if (!settled) {
          settled = true;
          resolve(ok);
        }
      };
      const req = http.get(
        {
          host: '127.0.0.1',
          port: BRAIN_PORT,
          path: '/health',
          timeout: timeoutMs,
        },
        (res) => {
          res.resume(); // drain so the socket frees up
          done(res.statusCode === 200);
        }
      );
      req.on('timeout', () => {
        req.destroy();
        done(false);
      });
      req.on('error', () => done(false));
      req.on('close', () => done(false));
    });

  /** PIDs LISTENing on the brain port (LISTEN-only so clients never match). */
  const brainListenerPids = () => {
    try {
      const out =
        spawnSync(
          'lsof',
          ['-nP', `-iTCP:${BRAIN_PORT}`, '-sTCP:LISTEN', '-t'],
          { encoding: 'utf8', timeout: 4000 }
        ).stdout || '';
      return out
        .split('\n')
        .map((s) => parseInt(s.trim(), 10))
        .filter((n) => Number.isInteger(n) && n > 0);
    } catch (_e) {
      return [];
    }
  };

  /** Poll /health until it answers or the timeout elapses. */
  const waitForBrain = async (timeoutMs) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (await probeBrain(2000)) {
        return true;
      }
      await sleep(750);
    }
    return false;
  };

  const reloadAllWindows = () => {
    for (const win of BrowserWindow.getAllWindows()) {
      try {
        if (!win.isDestroyed()) {
          win.webContents.reload();
        }
      } catch (_e) {
        /* best-effort */
      }
    }
  };

  /**
   * Kill whatever is LISTENing on the brain port and wait for a replacement.
   * The supervisor (BrainLauncher in a packaged app, scripts/brain.sh in dev)
   * sees the child exit and brings up a fresh brain.
   */
  const restartWedgedBrain = async (why) => {
    const pids = brainListenerPids();
    if (!pids.length) {
      logLine(
        `brain not listening on :${BRAIN_PORT} after wake (${why}) — ` +
          'waiting for the supervisor to (re)start it'
      );
      return waitForBrain(BRAIN_REVIVE_TIMEOUT_MS);
    }
    logLine(
      `restarting brain on :${BRAIN_PORT} (${why}) — pid(s) ${pids.join(', ')}`
    );
    for (const pid of pids) {
      try {
        process.kill(pid, 'SIGTERM');
      } catch (_e) {
        /* already gone */
      }
    }
    await sleep(1200);
    for (const pid of brainListenerPids()) {
      try {
        process.kill(pid, 'SIGKILL');
      } catch (_e) {
        /* already gone */
      }
    }
    if (await waitForBrain(BRAIN_REVIVE_TIMEOUT_MS)) {
      logLine(`brain back up on :${BRAIN_PORT}`);
      return true;
    }
    logLine(
      `brain did NOT come back on :${BRAIN_PORT} within ` +
        `${BRAIN_REVIVE_TIMEOUT_MS}ms — check ~/.undisclosed/logs/brain.log`
    );
    return false;
  };

  const recoverAfterWake = async (sleptMs) => {
    if (recoveryDisabled) {
      return;
    }
    const slept = sleptMs > 0 ? ` (asleep ${Math.round(sleptMs / 1000)}s)` : '';
    logLine(`power resume${slept} — running sleep/wake recovery`);

    const healthy = await probeBrain(4000);
    const force =
      FORCE_RESTART === 'always' ||
      (FORCE_RESTART !== 'never' &&
        (!healthy ||
          (sleptMs > 0 && sleptMs >= FORCE_RESTART_SLEEP_MS)));

    if (force) {
      // A brain that slept can still answer /health while its outbound sockets
      // and any in-flight turn are dead. Restart it so the UI reattaches to a
      // clean one — this is the "restart the brain by hand" step, automated.
      await restartWedgedBrain(
        healthy ? 'slept; recycling dead connections' : 'unresponsive on /health'
      );
    } else {
      logLine('brain healthy after resume — keeping it, recycling UI');
    }

    // Give the wake a beat to settle, then reload so the UI reattaches to a
    // (now healthy) brain instead of limping along on dead sockets.
    await sleep(RESUME_SETTLE_MS);
    reloadAllWindows();
  };

  let watchFailures = 0;
  let watchBusy = false;
  const startBrainWatchdog = () => {
    if ((process.env.UNDISCLOSED_DESKTOP_WATCHDOG || '1') === '0') {
      return;
    }
    const timer = setInterval(async () => {
      if (watchBusy) {
        return;
      }
      watchBusy = true;
      try {
        if (await probeBrain(4000)) {
          watchFailures = 0;
          return;
        }
        if (!brainListenerPids().length) {
          // Nothing listening: a cold start / the supervisor's job, not ours.
          watchFailures = 0;
          return;
        }
        watchFailures += 1;
        logLine(
          `brain /health probe failed (${watchFailures}/${WATCH_FAILS}) on :${BRAIN_PORT}`
        );
        if (watchFailures >= WATCH_FAILS) {
          watchFailures = 0;
          await restartWedgedBrain('watchdog: /health unresponsive');
          reloadAllWindows();
        }
      } finally {
        watchBusy = false;
      }
    }, WATCH_MS);
    if (timer.unref) {
      timer.unref();
    }
  };

  const registerPowerRecovery = () => {
    if (recoveryDisabled) {
      return;
    }
    startBrainWatchdog();
    if (!electron.powerMonitor) {
      return;
    }
    // Record when we went to sleep so 'resume' knows how long the gap was: a
    // brief display blip should not recycle the brain, a real sleep should.
    let sleepStartedAt = 0;
    electron.powerMonitor.on('suspend', () => {
      sleepStartedAt = Date.now();
    });
    electron.powerMonitor.on('resume', () => {
      const sleptMs = sleepStartedAt ? Date.now() - sleepStartedAt : 0;
      sleepStartedAt = 0;
      void recoverAfterWake(sleptMs);
    });
    logLine('sleep/wake recovery armed');
  };

  if (app.isReady()) {
    registerPowerRecovery();
  } else {
    app.once('ready', registerPowerRecovery);
  }
} catch (_e) {
  /* recovery wiring is best-effort; never prevent the app from starting */
}

require('./lib/backend/electron-main.js');
