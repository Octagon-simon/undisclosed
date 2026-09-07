#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Simon Ugorji
#
# Start/stop/logs the agent brain (FastAPI/uvicorn) in STANDALONE mode on :5001,
# using eigent-theia's own vendored brain + venv.
#
#   ./scripts/brain.sh setup     # provision the venv (delegates to setup-brain.sh)
#   ./scripts/brain.sh start     # start the brain (background)
#   ./scripts/brain.sh stop      # stop it
#   ./scripts/brain.sh restart
#   ./scripts/brain.sh logs      # tail the log
#   ./scripts/brain.sh status
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRAIN="$ROOT/brain"
PY="$BRAIN/.venv/bin/python"
PORT="${UNDISCLOSED_BRAIN_PORT:-5001}"
LOG="$ROOT/.brain.log"
PIDFILE="$ROOT/.brain.pid"
RUNFILE="$ROOT/.brain.run"  # exists while the dev brain is meant to be running

# NOTE: :5001 has (at most) ONE owner at a time. In the packaged desktop app the
# frozen `undisclosed-brain` sidecar is brought up by BrainLauncher (the Electron
# backend) and killed with the app. This script is DEV-ONLY. `start()` therefore
# refuses to double-launch if ANYTHING already owns the port (a leftover packaged
# app, a dev brain from another terminal, or an orphaned worker), and `stop()`
# cleans up BOTH our supervisor tree and any straggler still bound to the port —
# including an app-owned brain that outlived its parent. See brain.sh header notes.

supervisor_pids() { [ -f "$PIDFILE" ] && cat "$PIDFILE" 2>/dev/null || true; }

# Everything currently holding or listening on the brain port, as pid lines.
port_pids() { lsof -ti:"$PORT" 2>/dev/null || true; }

# The full supervisor (dev) process subtree rooted at the saved pidfile pid:
# the `( cd brain; while …; done ) &` subshell plus whatever python it spawned.
brain_tree_pids() {
  local sup pid
  sup="$(supervisor_pids)"
  [ -n "$sup" ] || return 0
  # `ps -o pgid` — the whole tree shares the supervisor's process-group id.
  local pg
  pg="$(ps -o pgid= -p "$sup" 2>/dev/null | tr -d ' ')"
  [ -n "$pg" ] && ps -eo pid=,pgid= 2>/dev/null | awk -v pg="$pg" '$2==pg{print $1}'
}

ensure_venv() {
  if [ ! -x "$PY" ]; then
    echo "[brain] venv missing — provisioning first…"
    "$ROOT/scripts/setup-brain.sh"
  fi
}

start() {
  ensure_venv
  if [ -n "$(port_pids)" ]; then
    echo "[brain] already running on :$PORT (pid(s): $(port_pids | tr '\n' ' '))"
    echo "[brain] refusing to double-launch. If a packaged desktop app owns it,"
    echo "[brain] quit that app and retry; if it is orphaned, run: ./scripts/brain.sh stop"
    return 1
  fi
  echo "[brain] starting on :$PORT (standalone, auto-restart)…"
  # Preserve the PREVIOUS run's log so a crash reason survives a restart
  # (truncating on every start wiped the evidence).
  [ -f "$LOG" ] && mv -f "$LOG" "$LOG.prev" 2>/dev/null || true
  touch "$RUNFILE"
  # Supervisor: keep the brain up. If it dies while RUNFILE exists (a crash,
  # not a `stop`), snapshot the crash log and respawn after a short backoff.
  (
    cd "$BRAIN" || exit 1
    while [ -f "$RUNFILE" ]; do
      UNDISCLOSED_BRAIN_PORT="$PORT" \
      UNDISCLOSED_BRAIN_HOST="${UNDISCLOSED_BRAIN_HOST:-127.0.0.1}" \
        "$PY" main.py >>"$LOG" 2>&1
      [ -f "$RUNFILE" ] || break   # a clean `stop` removed it → exit
      cp -f "$LOG" "$LOG.prev" 2>/dev/null || true
      echo "[brain] exited unexpectedly ($(date '+%H:%M:%S')); restarting in 2s…" >>"$LOG"
      sleep 2
    done
  ) &
  echo $! >"$PIDFILE"
  echo "[brain] supervisor pid $(cat "$PIDFILE") — logs: $LOG (previous: $LOG.prev)"
}

stop() {
  echo "[brain] stopping…"
  # 1) Tell the dev supervisor to stop respawning FIRST.
  rm -f "$RUNFILE"

  # 2) Clean up the dev supervisor subtree (group kill) if one is recorded.
  local tree
  tree="$(brain_tree_pids)"
  if [ -n "$tree" ]; then
    # shellcheck disable=SC2086
    kill $tree 2>/dev/null || true
  fi
  local sup
  sup="$(supervisor_pids)"
  if [ -n "$sup" ]; then
    # Escalate to SIGKILL if the supervisor ignores SIGTERM.
    sleep 0.3
    if ps -p "$sup" >/dev/null 2>&1; then
      kill -9 "$sup" 2>/dev/null || true
    fi
    rm -f "$PIDFILE"
  fi

  # 3) Whatever still holds :5001 (an app-owned brain whose parent quits later,
  #    or an orphaned worker) — tear it down too. Send TERM, then KILL stragglers
  #    so nothing survives half-dead.
  local pids
  pids="$(port_pids)"
  if [ -n "$pids" ]; then
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 0.5
    local leftover
    leftover="$(port_pids)"
    if [ -n "$leftover" ]; then
      echo "[brain] process(es) ignored SIGTERM; force-killing: $(echo $leftover | tr '\n' ' ')"
      # shellcheck disable=SC2086
      kill -9 $leftover 2>/dev/null || true
    fi
  fi

  if [ -n "$(port_pids)" ]; then
    echo "[brain] WARNING: :$PORT still in use after stop — inspect: lsof -i :$PORT"
    return 1
  fi
  echo "[brain] stopped — :$PORT clear"
}

status() {
  local pids
  pids="$(port_pids)"
  if [ -n "$pids" ]; then
    echo "[brain] running on :$PORT (pids: $(echo $pids | tr '\n' ' '))"
  else
    echo "[brain] not running"
  fi
}

case "${1:-start}" in
  setup) "$ROOT/scripts/setup-brain.sh" ;;
  start) start ;;
  stop) stop ;;
  restart) stop; sleep 1; start ;;
  logs) tail -f "$LOG" ;;
  status) status ;;
  *) echo "usage: $0 {setup|start|stop|restart|logs|status}" >&2; exit 1 ;;
esac
