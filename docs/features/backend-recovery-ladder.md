# Backend recovery: probe-gated ladder

**Problem.** When the renderer flips to "Offline - Cannot connect to backend."
(`theia-mod-offline` on `<body>`), the watchdog now relaunches the whole app as its
**first** action after ~5s. That is reliable but over-eager: it fires for two very
different failures with very different costs.

1. **Backend process alive, connection wedged.** The forked Theia node server is
   still up and answering, but the renderer's socket / a pooled socket went stale
   (the same stale-pooled-socket class we fixed for the post-wake `/api` 502). The
   process is fine and a reload re-establishes the connection.
2. **Backend process actually dead.** The forked node server crashed or was killed.
   Nothing but a restart brings it back.

Relaunch-first pays the maximum cost for both. It tears down the whole Electron app
**and** the brain sidecar (`:5001`, freed by the quit-time teardown sweep), so the
conversation and any in-flight agent session restart too, plus the quit is slow. The
user saw this: the window spun for a long time and did not come back cleanly.

**Decision (A, chosen).** Replace relaunch-first with a **probe-gated ladder**: probe
the backend port first, take the cheap recovery when the process is alive, and relaunch
only when it is actually dead. Drop the "fork a second backend in place" step from the
default path, because that is what flapped (offline -> live -> offline -> relaunch).

**Status:** implemented in `apps/desktop/electron-entry.js` (2026-10-15). The
default mode is now the ladder (`UNDISCLOSED_BACKEND_RECOVERY_MODE=auto`).

---

## Current behavior (what we have today)

All in `apps/desktop/electron-entry.js`, the "Theia BACKEND (node server) auto-recovery"
block (~lines 535-860):

- Watchdog samples the renderer every `UNDISCLOSED_BACKEND_WATCH_MS` (default 1000ms)
  via `readRendererState()`: it reads `theia-mod-offline` and the `?port=` query out of
  the live window. Acts after `UNDISCLOSED_BACKEND_OFFLINE_STRIKES` (default 5)
  consecutive offline reads, so ~5s of sustained offline.
- `UNDISCLOSED_BACKEND_RECOVERY_MODE` (default `relaunch`):
  - `relaunch` -> `autoRelaunch(port)` immediately: `app.relaunch(); app.quit()`,
    capped by `UNDISCLOSED_BACKEND_RELAUNCH_MAX` (default 3) threaded through
    `UNDISCLOSED_BACKEND_RELAUNCH_ATTEMPT`.
  - `inplace` -> `probeBackend(port, 3000)`:
    - answers -> `reloadAllWindows()`;
    - refused/timeout -> `restartBackendInPlace()` (fork a replacement via the
      `MainAppBridgeContribution` global, re-point windows at the new port);
    - bridge missing / fork failed / cap reached -> fall back to `autoRelaunch()`.
- `probeBackend(port, timeoutMs)` returns true on **any** HTTP response (even a 404),
  i.e. "a process is listening and answering".

## Why relaunch-first was wrong

- A wedged-but-alive backend sets `theia-mod-offline` exactly like a dead one. Relaunch
  cannot tell them apart, so it uses the sledgehammer on a socket problem.
- Relaunch is the most expensive option: full process restart, plus the brain restart
  that the teardown sweep causes, plus slow quit. It is the correct answer **only** for
  the dead case.
- The `inplace` mode's fork step is what flapped, so it should not be in the default
  path. But `inplace` also showed the useful half: the alive -> reload branch.

## Design: the ladder

On the existing ~5s sustained-offline trigger, in order:

1. **Probe** the backend port from the renderer's `?port=`, short timeout
   (~1500ms), via the existing `probeBackend()`.
2. **Alive -> reload.** `reloadAllWindows()`. This is the cheap recovery:
   - keeps the main process and the browser window alive,
   - keeps the **brain** (`:5001`) alive, because reload re-points the renderer at the
     *same* backend port and never touches the sidecar,
   - so the conversation history (persisted by the brain) and the agent session survive,
   - re-establishes the socket in ~2s instead of a full boot.
   Then re-check: if the renderer clears `theia-mod-offline`, done.
3. **Dead, or reload did not clear it -> relaunch.** `autoRelaunch(port)`, unchanged
   and still capped. This is now a true last resort, only for a dead backend.

Guards:

- Cap the reload rung, e.g. `UNDISCLOSED_BACKEND_RELOAD_MAX` (default 1), so a reload
  that cannot fix it escalates to relaunch instead of looping.
- Do **not** re-fork a second backend while the first may still exist; that is the flap
  source. The default mode never calls `restartBackendInPlace()`. Keep `inplace` as an
  opt-in for power users / debugging, or retire it, but it is not on the default path.

### Mode naming

- New default: the ladder, `UNDISCLOSED_BACKEND_RECOVERY_MODE=auto`. Chosen over
  re-aliasing `relaunch` so the value reads unambiguously; `~/.undisclosed/.env`
  (which pinned `relaunch`) was moved to `auto` at the same time.
- `relaunch` = always relaunch, no probe (the old behavior) for anyone who wants it.
- `inplace` unchanged, opt-in.

### New / changed knobs

- `UNDISCLOSED_BACKEND_PROBE_MS` (default 1500) - probe timeout before deciding.
- `UNDISCLOSED_BACKEND_RELOAD_MAX` (default 1) - reload attempts before relaunch.
- `UNDISCLOSED_BACKEND_WATCH_MS` / `UNDISCLOSED_BACKEND_OFFLINE_STRIKES` unchanged.
- `UNDISCLOSED_BACKEND_RELAUNCH_MAX` / `..._RELAUNCH_ATTEMPT` unchanged.

### Logging

Keep the existing strike line, then make the branch explicit so the log tells you which
rung fired:

```
backend offline in renderer (5/5)
backend alive on :PORT but renderer offline - reloading windows
# or
backend unreachable on :PORT - quitting and relaunching app (attempt 1/3)
# and, when a reload did not help:
reload did not clear offline - escalating to relaunch (attempt 1/3)
```

## Tradeoffs (honest)

- **Added latency in the dead case.** A probe (up to ~1.5s) runs before the relaunch, so
  a genuinely dead backend recovers ~1.5s later than today. The alive case is much
  faster, which is the point.
- **"Less disruptive" means faster + brain survives, not "zero state loss".** A reload
  still resets renderer-local UI (scroll position, open editors, an in-flight stream).
  The conversation itself reloads from the brain's store. Relaunch additionally restarts
  the brain, so it loses the agent session too. This is the real difference; both lose
  renderer-local state.
- **Does not fix a hung relaunch.** If the dead path does fire and the app still spins
  on quit (the slow brain-teardown sweep freeing `:5001`, or `app.quit()` not completing),
  that is a separate bug: bound the teardown, add a hard timeout, fall back to
  `app.exit()`. Flagged here so it is not mistaken for fixed.

## What this does not cover

- **Brain-vs-backend confusion.** The watchdog keys only on `theia-mod-offline` (the
  Theia node backend). The agent panel going offline because the **brain** is down is the
  other watchdog's job (the `:5001` health probe). Worth a sentence in the code so the
  two are not conflated further.
- **Alive but unrecoverable by reload.** Rare; the reload cap escalates to relaunch.

## Verification plan

- `node --check apps/desktop/electron-entry.js`.
- Packaged kill-test (cannot be done in this sandbox; needs a repackage):
  1. While the app runs, kill only the renderer's connection, e.g. SIGSTOP the backend
     node server so the port still answers -> expect the **alive -> reload** rung
     (`backend alive on :PORT ... reloading`), app stays open, conversation intact.
  2. SIGKILL the backend node server -> expect `backend unreachable ... relaunching`.
  3. Confirm a reload that cannot clear offline escalates within the cap.
- Watch `~/.undisclosed/logs/desktop-recovery.log` for the branch lines above.

## Open questions

- Probe timeout: 1500ms enough, or does a busy backend need longer to answer `/`?
- Reload cap: 1, or allow 2 with a longer grace?
- Should the ladder also cover the **brain** offline path, or keep them fully separate?
- Keep the `inplace` fork mode, or delete it now that the ladder makes it redundant?

## Where it lives

- Recovery logic: `apps/desktop/electron-entry.js` - `readRendererState`,
  `waitForBackendOnline`, `probeBackend`, `reloadAllWindows`, `autoRelaunch`,
  `restartBackendInPlace`, `startBackendWatchdog` (~lines 535-900).
- Brain watchdog (separate, `:5001`): same file, `startBrainWatchdog` / `recoverAfterWake`
  (~lines 186-510).
- Logs: `~/.undisclosed/logs/desktop-recovery.log`.
