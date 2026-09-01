#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Simon Ugorji
#
# Start/stop/logs the agent brain (FastAPI/uvicorn) in STANDALONE mode on :5001,
# using eigent-theia's own vendored brain + venv. This replaces "the eigent
# desktop app spawns the brain" — eigent-theia now runs its own.
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
PORT="${EIGENT_BRAIN_PORT:-5001}"
LOG="$ROOT/.brain.log"
PIDFILE="$ROOT/.brain.pid"
RUNFILE="$ROOT/.brain.run"  # exists while the brain is meant to be running

brain_pids() { lsof -ti:"$PORT" 2>/dev/null || true; }

ensure_venv() {
  if [ ! -x "$PY" ]; then
    echo "[brain] venv missing — provisioning first…"
    "$ROOT/scripts/setup-brain.sh"
  fi
}

start() {
  ensure_venv
  if [ -n "$(brain_pids)" ]; then
    echo "[brain] already running on :$PORT"
    return
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
      EIGENT_BRAIN_PORT="$PORT" \
      EIGENT_BRAIN_HOST="${EIGENT_BRAIN_HOST:-127.0.0.1}" \
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
  # Tell the supervisor to stop respawning FIRST, then kill the server.
  rm -f "$RUNFILE"
  local pids
  pids="$(brain_pids)"
  if [ -n "$pids" ]; then
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
  fi
  if [ -f "$PIDFILE" ]; then
    kill "$(cat "$PIDFILE")" 2>/dev/null || true
    rm -f "$PIDFILE"
  fi
  echo "[brain] stopped"
}

status() {
  local pids
  pids="$(brain_pids)"
  if [ -n "$pids" ]; then
    echo "[brain] running on :$PORT (pids: $pids)"
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
