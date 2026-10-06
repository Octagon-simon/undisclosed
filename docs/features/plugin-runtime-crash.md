# "Plugin runtime crashed unexpectedly" — root cause and fix

Investigated 2026-10-06 against the running dev app (`theia start`, http://localhost:3000),
`/tmp/theia.log`, and the macOS crash reports in `~/Library/Logs/DiagnosticReports`.

**Verdict: the toast is real but its hint is wrong.** The hosted plugin process was killed by
macOS's code-signing enforcement (`CODESIGNING` / `Invalid Page`), not by an out-of-memory kill.
The trigger is memory exhaustion, and a large share of that memory was a **leak**: every restart of
the dev server orphans its forked plugin host (and its language servers), and those orphans were
never reaped. Reaping them freed ~12 GB of swap (33.3 GB used -> 21.4 GB used).

---

## 1. Where the message comes from

`node_modules/@theia/plugin-ext/lib/hosted/node/hosted-plugin-process.js`:

```js
onChildProcessExit(serverName, pid, code, signal) {
    if (this.terminatingPluginServer) { return; }
    this.logger.error(`[${serverName}: ${pid}] IPC exited, with signal: ${signal}, and exit code: ${code}`);
    const message = 'Plugin runtime crashed unexpectedly, all plugins are not working, please reload the page.';
    let hintMessage = 'If it doesn\'t help, please check Theia server logs.';
    if (signal && signal.toUpperCase() === 'SIGKILL') {
        // May happen in case of OOM or manual force stop.
        hintMessage = 'Probably there is not enough memory for the plugins. ' + hintMessage;
    }
    this.messageService.error(message + ' ' + hintMessage, { timeout: 15 * 60 * 1000 });
}
```

So the exact wording you saw ("Probably there is not enough memory for the plugins.") is emitted
**only when the child died from signal SIGKILL**. The plugin host is forked as a plain node child
(`cp.fork(...)`, `execArgv: []`) out of the Theia backend, which is the process running
`lib/backend/main.js`.

`/tmp/theia.log` shows the matching backend lines — 20 of them, all SIGKILL:

```
root ERROR [hosted-plugin: 80504] IPC exited, with signal: SIGKILL, and exit code: null
```

## 2. What actually killed the process (not OOM)

macOS wrote a crash report for each one (`.ips`, `bug_type 309`). Every dev plugin-host crash since
11:29 has the same record:

```
procName : node
procPath : /Users/USER/*/node
parentProc: node        parentPid: 75368          <- the Theia backend
exception : EXC_BAD_ACCESS, signal "SIGKILL (Code Signature Invalid)"
termination: namespace CODESIGNING, indicator "Invalid Page"
```

The faulting thread is inside `process.dlopen` loading a native `.node` addon:

```
node::binding::DLOpen  (process.dlopen)
  node::Environment::TryLoadAddon
  dyld4::APIs::dlopen
  dyld4::Loader::getLoader / makeJustInTimeLoaderDisk
  mach_o::Universal::isUniversal
```

and the loaded image list is only 5 entries (node, dyld, one unnamed mapped file, libsystem_kernel,
libsystem_pthread) — it dies on the **first** native addon it maps.

So: the kernel killed the plugin host over a code page that failed signature validation. That is
neither Theia killing it, nor a userspace `kill`, nor the kernel's Jetsam/OOM path. Theia's
"not enough memory" hint is a misdiagnosis of *why* SIGKILL was used.

## 3. The real, fixable problem: orphaned plugin hosts

`ps` showed **25 orphaned dev plugin hosts** (parent PID 1) plus **80 of their children**
(tsserver, yaml/eslint/json language servers, devsense.php.ls, ...), some up to ~30 days old:

```
uid  pid  ppid  rss   command
...  3049  1     6 MB  .../eigent-theia/lib/backend/plugin-host
...  6992  1     7 MB  .../eigent-theia/lib/backend/plugin-host
... 24022  1     7 MB  .../eigent-theia/lib/backend/plugin-host
... 24047  24022 ...   tsserver.js --max-old-space-size=3072 ...
...
```

**Why they leak.** Theia forks the plugin host out of the backend, and the plugin host forks the
language servers. When the backend is stopped hard, nothing reaps them:

`scripts/dev.sh` did exactly that:

```sh
stop() {
  pids="$(port_pids)"                       # only the :3000 LISTENER
  echo "$pids" | xargs kill -9              # SIGKILL — no graceful shutdown possible
}
```

A SIGKILL of the backend gives Theia no chance to terminate its children, so the plugin host and its
language servers are reparented to `launchd` and run forever. `dev.sh restart` / `rebuild` repeat
this on every code change, so the orphans accumulate.

**Why it hurts.** Each orphan holds a plugin host (70 plugins) plus language servers
(`tsserver` alone is allowed `--max-old-space-size=3072`). Their pages are compressed/swapped, which
is why the RSS looked small (772 MB resident) but the swap cost was enormous. Under that pressure
the next fresh plugin host can be killed by the kernel during a native-addon page-in, which surfaces
as the toast.

Measured before/after reaping the orphans:

```
swap used before: 33310 MB / 34816 MB   (1505 MB free)
swap used after : 21412 MB / 27648 MB   (6235 MB free)
```

## 4. Fix: stop the leak at the source

`scripts/dev.sh` now reaps the whole tree:

- `kill_tree <pid>` walks `pgrep -P` recursively and kills children before the parent, so
  `dev.sh stop` reaps the plugin host and every language server under the backend.
- `reap_orphan_plugin_hosts` also catches orphans left by an earlier hard kill
  (`pgrep -f "$ROOT/lib/backend/plugin-host"`), **scoped to this repo's build output** so the
  packaged `Undisclosed.app` process tree is never touched.
- `stop()` calls both.

The already-leaked trees were reaped manually: 105 processes, swap 33.3 GB -> 21.4 GB.

## 5. Remaining follow-ups

- **The kernel code-signing kill itself** is mitigated (less memory pressure) but not fully pinned
  to a single addon. `node_modules/fsevents/fsevents.node` is the one native addon whose signature
  fails `codesign --verify` (linker-signed ad-hoc, fat x86_64+arm64); loading it standalone does not
  reproduce the kill, so it is a suspect, not a confirmed cause. If it recurs, either ad-hoc re-sign
  the native addons (`codesign --force --sign - <file>.node`) or capture the exact file by wrapping
  `process.dlopen` in the forked host.
- **The packaged app leaks too**: `Undisclosed.app` currently runs 18 plugin hosts. The same
  teardown question applies to `apps/desktop` (brain teardown / window close). Worth a look.
- **A separate crash class, and it *is* Electron.** The same report dump holds 20
  `Undisclosed Helper (Renderer)` crashes (19 `SIGABRT`, 1 `SIGTRAP`), and those are a different
  animal: `abort()` -> `node::OnFatalError` inside the **Electron Framework**, with V8
  `cppgc`/`CppHeap` frames. That is Electron's Chromium/V8, not the Node plugin host, so the
  Electron 30 -> 42.8.1 jump in the Theia upgrade is the relevant lever. Written up in
  `docs/plans/theia-upgrade-plan.md` section 3 ("Two different crashes, only one is Electron").
- The Theia 1.76 upgrade (`docs/plans/theia-upgrade-plan.md`) may change plugin-host teardown;
  re-check after the bump.

## 6. How to reproduce the diagnosis

```sh
# the message is emitted only for SIGKILL
grep -a "IPC exited" /tmp/theia.log | tail

# macOS says it was code-signing, not memory
python3 - <<'PY'
import json,os,glob
for p in sorted(glob.glob(os.path.expanduser("~/Library/Logs/DiagnosticReports/node-*.ips"))):
    raw=open(p,errors="replace").read(); body=json.loads(raw[raw.find("\n")+1:])
    print(os.path.basename(p), body.get("parentPid"), body.get("termination"))
PY

# leaked dev plugin hosts (parents already dead -> ppid 1)
ps -axo pid,ppid,etime,command | grep -F "eigent-theia/lib/backend/plugin-host" | grep -v grep
```
