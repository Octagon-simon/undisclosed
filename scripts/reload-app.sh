#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Simon Ugorji
#
# Rebuild the agent panel bundle and put it where the RUNNING app reads it, so a
# window reload (Cmd+R) is enough. No app rebuild, no relaunch.
#
#   ./scripts/reload-app.sh               build + install into the packaged app
#   ./scripts/reload-app.sh --check       typecheck agent-ui before building
#   ./scripts/reload-app.sh --brain       also restart the dev brain
#   ./scripts/reload-app.sh --no-install  only refresh the repo copy
#
# The panel bundle is served from disk (express.static) on every request, so
# replacing the file is enough: no Theia rebuild, because nothing under
# packages/ changed. Python edits are different — a running brain keeps the
# modules it imported, so this script warns when brain/app is newer than the
# brain process and restarts it only when asked (a restart drops task state).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ASSETS_REL="packages/undisclosed-agent/assets/agent-embed"
SRC="$ROOT/$ASSETS_REL"
BRAIN_PIDFILE="$ROOT/.brain.pid"

CHECK=0
BRAIN=0
INSTALL=1

usage() {
  cat <<'USAGE'
  ./scripts/reload-app.sh               build + install into the packaged app
  ./scripts/reload-app.sh --check       typecheck agent-ui before building
  ./scripts/reload-app.sh --brain       also restart the dev brain
  ./scripts/reload-app.sh --no-install  only refresh the repo copy

The panel bundle is served from disk on every request, so replacing the file is
enough: no Theia rebuild, because nothing under packages/ changed. Python edits
are different. A running brain keeps the modules it imported, so this script
warns when brain/app is newer than the brain process and restarts it only when
asked (a restart drops task state).
USAGE
}

for arg in "$@"; do
  case "$arg" in
    --check) CHECK=1 ;;
    --brain|--restart-brain) BRAIN=1 ;;
    --no-install) INSTALL=0 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[reload] unknown flag: $arg" >&2; usage; exit 2 ;;
  esac
done

say() { printf '[reload] %s\n' "$*"; }

if [ "$CHECK" = 1 ]; then
  say "typechecking agent-ui…"
  npm --prefix "$ROOT/agent-ui" run type-check
fi

say "building the agent panel bundle…"
(cd "$ROOT" && npm run build:agent-ui)

resolve_assets_dir() {
  local p="$1"
  if [ -d "$p/node_modules/undisclosed-agent/assets/agent-embed" ]; then
    printf '%s\n' "$p/node_modules/undisclosed-agent/assets/agent-embed"
    return 0
  fi
  if [ -d "$p/Contents/Resources/app/node_modules/undisclosed-agent/assets/agent-embed" ]; then
    printf '%s\n' "$p/Contents/Resources/app/node_modules/undisclosed-agent/assets/agent-embed"
    return 0
  fi
  return 1
}

installed=0
if [ "$INSTALL" = 1 ]; then
  candidates=()
  [ -n "${UNDISCLOSED_APP_PATH:-}" ] && candidates+=("$UNDISCLOSED_APP_PATH")
  candidates+=("/Applications/Undisclosed.app" "$HOME/Applications/Undisclosed.app")
  candidates+=("$ROOT/apps/desktop/dist/mac-arm64/Undisclosed.app" "$ROOT/apps/desktop/dist/mac/Undisclosed.app")

  for candidate in "${candidates[@]}"; do
    [ -e "$candidate" ] || continue
    dst="$(resolve_assets_dir "$candidate")" || continue
    cp "$SRC/agent-embed.umd.js" "$SRC/style.css" "$dst/"
    say "installed into $dst"
    installed=$((installed + 1))
    break
  done

  if [ "$installed" = 0 ]; then
    say "no packaged app found (set UNDISCLOSED_APP_PATH to its .app)."
    say "repo copy refreshed; a dev server (./scripts/dev.sh) serves it directly."
  fi
fi

if [ "$BRAIN" = 1 ]; then
  say "restarting the brain…"
  bash "$ROOT/scripts/brain.sh" restart
elif [ -f "$BRAIN_PIDFILE" ] && \
     [ -n "$(find "$ROOT/brain/app" "$ROOT/brain/main.py" -name '*.py' -newer "$BRAIN_PIDFILE" -print -quit 2>/dev/null)" ]; then
  say "brain/app has Python edits newer than the running brain."
  say "the panel changes work on reload; the Python ones need: $0 --brain"
fi

if pgrep -f "Undisclosed.app/Contents/MacOS/Undisclosed" >/dev/null 2>&1; then
  say "done. Reload the window now: Cmd+R (Ctrl+R on Windows/Linux)."
else
  say "done. The app is not running; start it and the new bundle loads."
fi
