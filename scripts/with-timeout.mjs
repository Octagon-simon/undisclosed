#!/usr/bin/env node
// Run a command under a hard wall-clock timeout, killing the whole process tree.
//
//   node scripts/with-timeout.mjs <seconds> <command> [args...]
//
// Why this exists: `theia download:plugins` fetches from open-vsx over sockets
// with no timeout, so a stalled connection hangs forever (an Intel macOS runner
// sat there for 1h30m+). POSIX `timeout` is not present on GitHub's macOS
// runners, but node always is.
//
// On SIGINT/SIGTERM/SIGHUP we forward the kill to the child's process tree, so a
// caller that decides the work is done early (see ci-download-plugins.sh) can
// stop the command without orphaning npm/theia behind it.
//
// Exit code: the command's own code, 124 when killed for exceeding the timeout,
// 130 when the parent signalled us to stop, 127 if the command could not start.
import { spawn } from 'node:child_process';

const [secondsRaw, command, ...args] = process.argv.slice(2);
const seconds = Number(secondsRaw);
if (!command || !Number.isFinite(seconds) || seconds <= 0) {
  console.error('usage: with-timeout.mjs <seconds> <command> [args...]');
  process.exit(2);
}

const isWindows = process.platform === 'win32';
const child = spawn(command, args, {
  stdio: 'inherit',
  // Own process group on POSIX so we can SIGKILL the whole tree
  // (npm -> theia -> node). Windows gets taskkill /T instead.
  detached: !isWindows,
  // Windows needs a shell to resolve npm/npx.cmd shims.
  shell: isWindows,
});

let reason; // 'timeout' | 'signal'
function killTree() {
  try {
    if (isWindows) {
      spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
    } else {
      process.kill(-child.pid, 'SIGKILL');
    }
  } catch {
    // Process already gone.
  }
}

const timer = setTimeout(() => {
  reason = 'timeout';
  killTree();
}, seconds * 1000);

for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  process.on(sig, () => {
    reason = 'signal';
    killTree();
    process.exit(130);
  });
}

child.on('exit', (code, signal) => {
  clearTimeout(timer);
  if (reason === 'timeout') {
    console.error(`\n[with-timeout] command exceeded ${seconds}s and was killed`);
    process.exit(124);
  }
  if (reason === 'signal') {
    process.exit(130);
  }
  process.exit(typeof code === 'number' ? code : signal ? 1 : 0);
});

child.on('error', err => {
  clearTimeout(timer);
  console.error(`[with-timeout] failed to start '${command}': ${err.message}`);
  process.exit(127);
});
