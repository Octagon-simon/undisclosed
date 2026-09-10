  #!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Simon Ugorji
#
# Dev helper for the Eigent-Theia editor. Manages the local Theia server on
# port 3000 so you don't have to remember the kill/build/start dance.
#
# Usage:
#   ./scripts/dev.sh start      # start the server (background)
#   ./scripts/dev.sh stop       # stop whatever holds port 3000
#   ./scripts/dev.sh restart    # stop + start
#   ./scripts/dev.sh build      # rebuild extension + Theia frontend
#   ./scripts/dev.sh rebuild    # build + restart (full refresh)
#   ./scripts/dev.sh logs       # tail the server log
#   ./scripts/dev.sh status     # is it up? which pid?
#   ./scripts/dev.sh brain ...  # manage the agent brain (see scripts/brain.sh)
#
# start/stop/restart bring up BOTH the Theia editor (:3000) and the agent brain
# (:5001) — eigent-theia now runs its own brain (no eigent desktop app needed).
#
# Add a shorter alias if you like:
#   alias theia='~/Documents/github/eigent-theia/scripts/dev.sh'

set -euo pipefail

PORT=3000
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$ROOT/.theia-server.log"
BRAIN_SH="$ROOT/scripts/brain.sh"

# Pin Node 20 (Theia's native builds break on newer Node). Prefer the nvm-
# installed v20 if present, else fall back to whatever `node` is on PATH.
NODE20="$HOME/.nvm/versions/node/v20.20.2/bin"

# Point the editor's /api proxy at eigent-theia's OWN local brain (:5001)
# instead of the old external eigent backend (default :3001). This is what makes
# eigent-theia self-sufficient — no eigent/server Docker stack needed.
export UNDISCLOSED_PROXY_TARGET="${UNDISCLOSED_PROXY_TARGET:-http://localhost:5001}"

if [ -d "$NODE20" ]; then
  export PATH="$NODE20:$PATH"
fi

cd "$ROOT"

is_up() { curl -s -o /dev/null -w "%{http_code}" "http://localhost:$PORT" 2>/dev/null | grep -q 200; }
# LISTEN-only: `lsof -ti:PORT` also matches processes CONNECTED to :PORT (e.g. a
# browser tab or the agent panel), which stop() would then kill. Only ever match
# the Theia server that's actually listening.
port_pids() { lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null || true; }

stop() {
  local pids
  pids="$(port_pids)"
  if [ -n "$pids" ]; then
    echo "stopping server on :$PORT (pids: $pids)"
    echo "$pids" | xargs kill -9 2>/dev/null || true
    sleep 1
  fi
  if [ -z "$(port_pids)" ]; then echo "port $PORT: free"; else echo "port $PORT: still busy ($(port_pids | tr '\n' ' '))"; fi
  "$BRAIN_SH" stop || true
}

start() {
  # Bring up the agent brain first (idempotent) so the panel has a backend.
  "$BRAIN_SH" start || echo "warning: brain failed to start (see .brain.log)"
  if is_up; then
    echo "already up at http://localhost:$PORT"
    return 0
  fi
  echo "starting Theia (log: $LOG)"
  nohup npm run start >"$LOG" 2>&1 &
  echo "started pid $!"
  wait_ready
}

wait_ready() {
  for i in $(seq 1 60); do
    if is_up; then echo "READY (HTTP 200) after ${i}s -> http://localhost:$PORT"; return 0; fi
    sleep 1
  done
  echo "did not become ready in 60s; tail of log:"; tail -20 "$LOG" || true
  return 1
}

build() {
  # Each step is guarded so one failure is REPORTED (with a clear marker) rather
  # than silently aborting the whole rebuild. Returns non-zero if anything failed.
  local ok=0
  echo "== build agent UI bundle (agent-ui -> assets) =="
  npm run build:agent-ui || { echo "❌ agent-ui build FAILED"; ok=1; }
  echo "== build undisclosed-agent extension (tsc) =="
  npm run build --prefix packages/undisclosed-agent || { echo "❌ undisclosed-agent (tsc) build FAILED"; ok=1; }
  echo "== theia build (development) =="
  npm run build || { echo "❌ theia build FAILED"; ok=1; }
  return $ok
}

case "${1:-restart}" in
  start)   start ;;
  stop)    stop ;;
  restart) stop; start ;;
  build)   build ;;
  # ALWAYS restart Theia + brain, even if the build errored, so a bad build can
  # never leave you backend-less. The ❌ markers above tell you what failed.
  rebuild)
    if build; then echo "✅ build OK"; else echo "⚠️  BUILD HAD ERRORS (see ❌ above) — restarting anyway"; fi
    stop; start ;;
  logs)    tail -f "$LOG" ;;
  status)
    if is_up; then echo "Theia: UP (HTTP 200) pids: $(port_pids | tr '\n' ' ')"; else echo "Theia: DOWN"; fi
    "$BRAIN_SH" status ;;
  brain)   shift; "$BRAIN_SH" "${1:-status}" ;;
  *)
    echo "usage: $0 {start|stop|restart|build|rebuild|logs|status|brain <cmd>}" >&2
    exit 2 ;;
esac
