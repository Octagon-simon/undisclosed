#!/usr/bin/env node
// Run a command under a hard wall-clock timeout, killing the whole process tree.
//
//   node scripts/with-timeout.mjs <seconds> <command> [args...]
//
// Why this exists: `theia download:plugins` fetches from open-vsx over sockets
// with no timeout, so a stalled connection hangs forever (an Intel macOS runner
// sat there for 1h30m+). POSIX `timeout` is not present on GitHub's macOS
// runners, but node always is. Exit code: the command's own code, or 124 when it
// was killed for exceeding the timeout.
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

let killed = false;
const timer = setTimeout(() => {
  killed = true;
  try {
    if (isWindows) {
      spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
    } else {
      process.kill(-child.pid, 'SIGKILL');
    }
  } catch {
    // Process already gone.
  }
}, seconds * 1000);

child.on('exit', (code, signal) => {
  clearTimeout(timer);
  if (killed) {
    console.error(`\n[with-timeout] command exceeded ${seconds}s and was killed`);
    process.exit(124);
  }
  process.exit(typeof code === 'number' ? code : signal ? 1 : 0);
});

child.on('error', err => {
  clearTimeout(timer);
  console.error(`[with-timeout] failed to start '${command}': ${err.message}`);
  process.exit(127);
});
