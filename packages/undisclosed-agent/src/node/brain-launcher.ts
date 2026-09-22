// Copyright (c) 2026 Simon Ugorji

import { injectable } from '@theia/core/shared/inversify';
import { BackendApplicationContribution } from '@theia/core/lib/node';
import { ChildProcess, spawn, spawnSync } from 'child_process';
import * as fs from 'fs';
import * as http from 'http';
import * as os from 'os';
import * as path from 'path';

/**
 * True if something is already LISTENing on `port` (POSIX + Windows best-effort).
 *
 * `:5001` must have exactly ONE owner. macOS happily lets a second process bind
 * the SAME port on a different address (`*:5001` next to `127.0.0.1:5001`), so a
 * packaged app launched while a dev brain is up creates TWO listeners on one
 * port. Connections then race between them (some hit a stale/idle brain → chat
 * looks dead or "takes many turns"), and whichever brain the app did not adopt
 * survives as an orphan holding the port. This guard makes the packaged launcher
 * defer to an existing owner instead of double-binding. Query is LISTEN-only so
 * transient CLIENT sockets to the port never count as an owner.
 */
function portInUse(port: number): boolean {
  try {
    if (process.platform === 'win32') {
      const out = spawnSync('netstat', ['-ano'], { encoding: 'utf8' }).stdout;
      return new RegExp(`:${port}\\b.*LISTENING\\s+\\d+\\s*$`, 'im').test(out);
    }
    const out = spawnSync(
      'lsof',
      ['-nP', `-iTCP:${port}`, '-sTCP:LISTEN', '-t'],
      { encoding: 'utf8' }
    ).stdout;
    return out.trim().length > 0;
  } catch {
    // If the probe itself fails, do NOT block startup — fall through and spawn.
    return false;
  }
}

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

  /** Set once onStop() begins; suppresses exit-triggered respawn. */
  private stopping = false;
  /** Health watchdog interval handle (unref'd; cleared on stop). */
  private watchdogTimer: NodeJS.Timeout | undefined;
  /** Consecutive failed /health probes since the last success. */
  private failures = 0;
  /** Whether the brain has answered /health at least once this session. */
  private healthyOnce = false;
  /** When this watchdog started — used for the cold-start grace window. */
  private watchdogStartedAt = 0;
  /** Count of automatic respawns, to cap a crash-loop. */
  private restartCount = 0;
  /** When the current brain generation was spawned (0 until the first spawn). */
  private childStartedAt = 0;
  /** Append-only fd the frozen brain's stdout/stderr is captured to. */
  private brainLogFd: number | undefined;

  /** How often the watchdog probes /health. */
  private static readonly WATCH_INTERVAL_MS = 10_000;
  /** Grace period after (re)start before /health failures count (cold start). */
  private static readonly STARTUP_GRACE_MS = 60_000;
  /** Delay before an unexpected-exit respawn. */
  private static readonly RESPAWN_MS = 2_000;
  /** Maximum automatic respawns before giving up. */
  private static readonly MAX_RESTARTS = 10;
  /**
   * A brain that has stayed continuously healthy this long is not a crash-loop,
   * so its restart budget is forgiven. Without this, a session with many
   * sleep/wake cycles (each a legitimate restart) eventually hits MAX_RESTARTS
   * and auto-recovery stops for good — the "I have to restart the brain by hand
   * now" the user sees after a few sleeps.
   */
  private static readonly HEALTHY_RESET_MS = 5 * 60_000;

  /** macOS/Linux support negative-PID (process-group) signalling; Windows does not. */
  private static posixGroups(): boolean {
    return process.platform !== 'win32';
  }

  /** Id to signal: the negative pid (the whole group) on POSIX, the plain pid on Windows. */
  private static groupOfChild(pid: number): number {
    return BrainLauncher.posixGroups() ? -pid : pid;
  }

  onStart(): void {
    // Expose this instance so the backend REST route can service a
    // user-triggered brain restart from the agent panel.
    BrainLauncher.current = this;
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

    // Single-owner guard: if :port already has a listener (a dev brain from
    // scripts/brain.sh, or another instance), defer to it instead of spawning a
    // second, detached brain. brain.sh already refuses to double-launch; this
    // closes the reverse case the script cannot see (packaged app started
    // second). Double-binding is what makes chat nondeterministic and leaves an
    // orphan brain holding :5001.
    if (portInUse(Number(port))) {
      // eslint-disable-next-line no-console
      console.log(
        `[brain-launcher] :${port} already has a listener — not spawning a ` +
          'second brain (single-owner guard). Existing owner will serve requests.'
      );
      return;
    }

    this.spawnChild(bin, port);
    this.startWatchdog(bin, port);
  }

  /**
   * Spawn the brain as a group-leading, detached child, and re-spawn it if it
   * ever exits while the app is still running.
   *
   * This mirrors what scripts/brain.sh does in dev: the brain is meant to be
   * up for the whole session, so an unexpected exit (a crash, an OOM, a Python
   * traceback under a bad turn) should not leave the editor with a dead backend
   * that only a manual `brain.sh start` can revive. Respawn is suppressed while
   * onStop() is tearing the app down.
   */
  private spawnChild(bin: string, port: string): void {
    // eslint-disable-next-line no-console
    console.log(`[brain-launcher] starting brain: ${bin} on :${port}`);

    const logFd = this.openBrainLogFd();
    const proc = spawn(bin, [], {
      env: { ...process.env, UNDISCLOSED_BRAIN_PORT: port },
      // Capture the brain's own stdout/stderr to a file. In a packaged app
      // `inherit` goes to the unified log, so a brain that wedges or dies after
      // a sleep leaves nothing to diagnose. Fall back to inherit if the file
      // cannot be opened.
      stdio: logFd === undefined ? 'inherit' : ['ignore', logFd, logFd],
      // detached: true makes the child the leader of a brand-new process group,
      // isolating it (and everything it spawns) from Electron's group so we can
      // signal it as one unit. We never unref(): the launcher owns the child for
      // the whole lifetime of the app.
      detached: BrainLauncher.posixGroups(),
    });
    this.proc = proc;
    this.childStartedAt = Date.now();

    proc.on('error', (err) => {
      // eslint-disable-next-line no-console
      console.error(`[brain-launcher] failed to start brain: ${err.message}`);
      if (this.proc === proc) {
        this.proc = undefined;
      }
    });
    proc.on('exit', (code, signal) => {
      // eslint-disable-next-line no-console
      console.error(
        `[brain-launcher] brain exited (code=${code}, signal=${signal})`
      );
      if (this.proc === proc) {
        this.proc = undefined;
      }
      if (this.stopping) {
        return;
      }
      // Unexpected exit — bring it back. Cap a crash-loop so we don't spin
      // forever on a brain that cannot start (it will surface as repeated
      // "brain exited" lines instead of a silent, permanently-dead backend).
      if (this.restartCount >= BrainLauncher.MAX_RESTARTS) {
        // eslint-disable-next-line no-console
        console.error(
          `[brain-launcher] brain restarted ${this.restartCount} times — ` +
            'giving up automatic respawn; restart the app or run scripts/brain.sh'
        );
        return;
      }
      this.restartCount += 1;
      // eslint-disable-next-line no-console
      console.warn(
        `[brain-launcher] respawning brain in ${BrainLauncher.RESPAWN_MS}ms ` +
          `(restart ${this.restartCount}/${BrainLauncher.MAX_RESTARTS})`
      );
      setTimeout(() => {
        if (!this.stopping) {
          this.spawnChild(bin, port);
        }
      }, BrainLauncher.RESPAWN_MS).unref?.();
    });
  }

  /**
   * Periodically probe the brain's /health. If it stays unreachable for
   * UNDISCLOSED_BRAIN_WATCH_FAILS consecutive probes (after having been healthy
   * at least once, and past the startup grace), the loop is wedged — the exact
   * state a macOS sleep/wake leaves behind (half-open sockets, a stuck
   * model/tool call) — so we kill the group and let spawnChild()'s exit handler
   * bring up a fresh one.
   *
   * Conservative by design: a probe must fail for ~1 minute before we act, and
   * a brain that has never answered is left alone (it may still be importing,
   * which can take a while on a cold start). Disable with
   * UNDISCLOSED_BRAIN_WATCHDOG=0.
   */
  private startWatchdog(bin: string, port: string): void {
    const enabled =
      (process.env.UNDISCLOSED_BRAIN_WATCHDOG ?? '1').trim().toLowerCase() !==
      '0';
    if (!enabled || this.watchdogTimer) {
      return;
    }
    const nodePort = Number(port);
    const failThreshold = Number(process.env.UNDISCLOSED_BRAIN_WATCH_FAILS || 3);
    this.watchdogStartedAt = Date.now();
    this.watchdogTimer = setInterval(() => {
      void this.watchdogTick(bin, nodePort, failThreshold);
    }, BrainLauncher.WATCH_INTERVAL_MS);
    this.watchdogTimer.unref?.();
  }

  private async watchdogTick(
    bin: string,
    port: number,
    failThreshold: number
  ): Promise<void> {
    if (this.stopping || !this.proc) {
      return;
    }
    const healthy = await BrainLauncher.probeHealth(port);
    if (healthy) {
      this.failures = 0;
      this.healthyOnce = true;
      // Sustained health means this is not a crash-loop: forgive the restart
      // budget so repeated sleep/wake restarts never exhaust MAX_RESTARTS.
      if (
        this.restartCount > 0 &&
        this.childStartedAt &&
        Date.now() - this.childStartedAt >= BrainLauncher.HEALTHY_RESET_MS
      ) {
        this.restartCount = 0;
      }
      return;
    }
    if (
      !this.healthyOnce &&
      Date.now() - this.watchdogStartedAt < BrainLauncher.STARTUP_GRACE_MS
    ) {
      return; // still starting up — do not judge yet
    }
    this.failures += 1;
    // eslint-disable-next-line no-console
    console.warn(
      `[brain-launcher] /health probe failed (${this.failures}/${failThreshold})`
    );
    if (this.failures < failThreshold) {
      return;
    }
    // eslint-disable-next-line no-console
    console.error(
      '[brain-launcher] brain unresponsive on /health — restarting it'
    );
    this.failures = 0;
    this.healthyOnce = false;
    this.watchdogStartedAt = Date.now();
    const proc = this.proc;
    if (proc?.pid) {
      try {
        // Kill the whole group so a wedged worker cannot keep the port.
        process.kill(BrainLauncher.groupOfChild(proc.pid), 'SIGKILL');
      } catch {
        /* ESRCH — already gone; the exit handler will respawn */
      }
    }
    // If the process was already gone, no 'exit' will fire — respawn directly.
    if (!this.proc && !this.stopping) {
      this.spawnChild(bin, String(port));
    }
  }

  /** One-shot /health probe against the local brain. True only on HTTP 200. */
  private static probeHealth(port: number): Promise<boolean> {
    return new Promise((resolve) => {
      const req = http.get(
        { host: '127.0.0.1', port, path: '/health', timeout: 3000 },
        (res) => {
          res.resume(); // drain so keep-alive sockets free up
          resolve(res.statusCode === 200);
        }
      );
      req.on('timeout', () => req.destroy());
      req.on('error', () => resolve(false));
      req.on('close', () => resolve(false));
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
    this.stopping = true;
    if (this.watchdogTimer) {
      clearInterval(this.watchdogTimer);
      this.watchdogTimer = undefined;
    }
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

  /**
   * Open (once) an append-only log for the frozen brain's stdout/stderr, under
   * ~/.undisclosed/logs/brain.log. Rotated once past a size cap so a wedged
   * brain's last words survive its respawn. Returns undefined (caller falls back
   * to stdio:'inherit') if the file cannot be opened.
   */
  private openBrainLogFd(): number | undefined {
    if (this.brainLogFd !== undefined) {
      return this.brainLogFd;
    }
    try {
      const dir = path.join(
        process.env.UNDISCLOSED_DATA_DIR ||
          path.join(os.homedir(), '.undisclosed'),
        'logs'
      );
      fs.mkdirSync(dir, { recursive: true });
      const file = path.join(dir, 'brain.log');
      try {
        if (fs.statSync(file).size > 16 * 1024 * 1024) {
          fs.renameSync(file, path.join(dir, 'brain.log.prev'));
        }
      } catch {
        /* no existing log to rotate */
      }
      this.brainLogFd = fs.openSync(file, 'a');
    } catch {
      this.brainLogFd = undefined;
    }
    return this.brainLogFd;
  }

  /**
   * The most recently constructed launcher (singleton in practice — bound
   * inSingletonScope). Lets the backend REST route reach the live instance to
   * service a user-triggered "resurrect the brain" from the agent panel.
   */
  static current: BrainLauncher | undefined;

  /** True when this launcher can actually spawn a brain (a frozen binary is
   *  present — i.e. the packaged app). False in a dev build, where the brain is
   *  run from source via scripts/brain.sh; the restart route falls through to
   *  the script in that case. */
  canManage(): boolean {
    return this.resolveBinary() !== undefined;
  }

  /**
   * Resurrect the brain on demand (agent-panel Restart button). Works for the
   * PACKAGED app — the case scripts/brain.sh can't cover: kill any child we own,
   * wait for the port to free, then spawn our frozen brain. This also fixes the
   * external-brain dance: the user stops their standalone brain → port frees →
   * clicks Restart → the packaged app brings up ITS OWN frozen brain, so it no
   * longer depends on the external one being restarted by hand.
   *
   * Returns a short status string. Never throws.
   */
  async restart(): Promise<{ ok: boolean; detail: string }> {
    const bin = this.resolveBinary();
    if (!bin) {
      return {
        ok: false,
        detail:
          'No frozen brain binary found (dev build). Run scripts/brain.sh restart.',
      };
    }
    const port = process.env.UNDISCLOSED_BRAIN_PORT || '5001';

    // Reset the crash-loop budget: a user-initiated restart is intentional.
    this.restartCount = 0;
    this.stopping = false;

    // 1) Tear down a child we own (if any).
    try {
      this.onStop();
    } catch {
      /* best-effort */
    }
    this.stopping = false; // onStop set it; clear so respawn/watchdog work again

    // 2) Wait (up to ~5s) for :port to be free — an externally-owned brain the
    //    user just stopped may take a moment to release the socket.
    for (let i = 0; i < 25 && portInUse(Number(port)); i++) {
      await new Promise((r) => setTimeout(r, 200));
    }
    if (portInUse(Number(port))) {
      return {
        ok: false,
        detail: `:${port} is still held by another process; could not take it over.`,
      };
    }

    // 3) Spawn our frozen brain and re-arm the watchdog.
    try {
      this.spawnChild(bin, port);
      this.startWatchdog(bin, port);
      return { ok: true, detail: `Spawning brain on :${port}.` };
    } catch (err) {
      return { ok: false, detail: (err as Error).message };
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
