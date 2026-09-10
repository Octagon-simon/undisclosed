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

# The process LISTENING on the brain port, as pid lines. MUST be LISTEN-only:
# `lsof -ti:PORT` also matches CLIENTS connected TO :PORT (either endpoint), so
# when the packaged app's Theia backend holds a proxied `/api` SSE connection to
# the brain (panel open on a conversation), the plain query returns the BACKEND
# too — and stop() would SIGKILL the editor's backend, dropping its :53701
# socket.io and knocking the whole editor offline. `-sTCP:LISTEN` excludes
# clients so we only ever kill the brain itself.
port_pids() { lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null || true; }

# Poll until :PORT has no owner, up to $1 seconds. Returns 0 once clear, 1 on
# timeout. Used to wait out a graceful (uvicorn) shutdown before escalating —
# the old one-shot `sleep 0.5` recheck fired before the socket was released and
# made `stop` report a false "still in use".
wait_port_clear() {
  local end=$((SECONDS + ${1:-3}))
  while [ "$SECONDS" -lt "$end" ]; do
    [ -z "$(port_pids)" ] && return 0
    sleep 0.25
  done
  [ -z "$(port_pids)" ]
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
  # 1) Tell the dev supervisor to stop respawning FIRST, so once the child dies
  #    it is not brought back.
  rm -f "$RUNFILE"

  # 2) Kill the supervisor subshell if one is recorded. (Killing it ORPHANS the
  #    python child — it keeps the port — so step 3 targets the port owner
  #    directly rather than relying on a process-group kill, which here could
  #    hit this script's own group.)
  local sup
  sup="$(supervisor_pids)"
  if [ -n "$sup" ]; then
    kill "$sup" 2>/dev/null || true
    sleep 0.2
    ps -p "$sup" >/dev/null 2>&1 && kill -9 "$sup" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"

  # 3) Tear down whatever still holds :PORT — the (now orphaned) python child, an
  #    app-owned brain that outlived its parent, or an orphaned worker. TERM and
  #    WAIT for a graceful exit (uvicorn shutdown can take a couple seconds);
  #    only then escalate to SIGKILL. The wait is what the old one-shot recheck
  #    lacked, which is why stragglers survived and `stop` falsely returned 1.
  local pids
  pids="$(port_pids)"
  if [ -n "$pids" ]; then
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    if ! wait_port_clear 3; then
      pids="$(port_pids)"
      if [ -n "$pids" ]; then
        echo "[brain] process(es) ignored SIGTERM; force-killing: $(echo $pids | tr '\n' ' ')"
        # shellcheck disable=SC2086
        kill -9 $pids 2>/dev/null || true
        wait_port_clear 3 || true
      fi
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
  # `stop` may return non-zero (e.g. the port is genuinely wedged); under
  # `set -e` that would abort before `start` ever ran — which is why `restart`
  # used to just print "stopping…" and quit. Tolerate it and let `start` report.
  restart) stop || true; start ;;
  logs) tail -f "$LOG" ;;
  status) status ;;
  *) echo "usage: $0 {setup|start|stop|restart|logs|status}" >&2; exit 1 ;;
esac
