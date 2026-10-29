#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Simon Ugorji
#
# Move the machine onto the PACKAGED build so the desktop toolkit runs inside a
# brain that inherits the app's Accessibility grant:
#   quit the running app -> free :5001 from the dev brain -> launch the packaged
#   app -> confirm the app's own frozen brain answers. Falls back to the dev
#   brain if the packaged sidecar never comes up.
#
#   scripts/relaunch-for-desktop-test.sh [--keep-brain] [path/to/Undisclosed.app]
#
# --keep-brain leaves :PORT alone. Use it when UNDISCLOSED_BRAIN_SELF_HOSTED is
# set: the app will not spawn a brain of its own, so freeing the port only leaves
# chat offline until something starts one again.
#
# Run it detached (nohup ... &): stopping the dev brain kills the agent session
# that would otherwise report the result, which is why the heads-up goes out on
# the notify-user channel first.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/apps/desktop/dist/mac-arm64/Undisclosed.app"
KEEP_BRAIN=0
for arg in "$@"; do
  case "$arg" in
    --keep-brain) KEEP_BRAIN=1 ;;
    *) APP="$arg" ;;
  esac
done
PORT="${UNDISCLOSED_BRAIN_PORT:-5001}"
LOG="${TMPDIR:-/tmp}/desktop-test-relaunch.log"
VERIFY="${TMPDIR:-/tmp}/desktop-test-verify.log"
DELAY="${RELAUNCH_DELAY:-45}"

: > "$LOG"
say() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG"; }
health() { curl -s -m 3 "http://127.0.0.1:$PORT/health"; }
port_busy() { lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; }

say "target app: $APP"
if [ ! -d "$APP" ]; then
  say "no such app bundle; aborting"
  exit 1
fi
BUNDLE_ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' \
  "$APP/Contents/Info.plist" 2>/dev/null)"
say "bundle id: ${BUNDLE_ID:-unknown}"
if [ ! -x "$APP/Contents/Resources/brain/undisclosed-brain" ]; then
  say "WARNING: bundle has no frozen brain; the app will not start one"
fi

# Heads-up first, while the app is still alive.
if [ "${RELAUNCH_NOTIFY:-1}" = 1 ]; then
  nohup "$ROOT/scripts/notify-user.sh" \
    --title "Undisclosed" \
    --subtitle "Switching to the packaged build" \
    --message "Quitting the editor, freeing :$PORT from the dev brain, and launching ${BUNDLE_ID:-the packaged build} in ${DELAY}s. Grant Accessibility to that app when it asks, then say 'desktop status'." \
    >/dev/null 2>&1 &
fi

say "waiting ${DELAY}s before touching anything"
sleep "$DELAY"

# Any build can be running, not just the one we are switching to; the app holds a
# single-instance lock, so the old build has to go or the new one exits on launch.
ANY_APP="Undisclosed.app/Contents/MacOS/Undisclosed"
RUNNING_PID="$(pgrep -f "$ANY_APP" | head -1)"
if [ -n "$RUNNING_PID" ]; then
  RUNNING_APP="$(ps -o command= -p "$RUNNING_PID" \
    | sed -E 's#(.*\.app)/Contents/MacOS/Undisclosed.*#\1#')"
  RUNNING_ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' \
    "$RUNNING_APP/Contents/Info.plist" 2>/dev/null)"
  say "quitting the running app (pid $RUNNING_PID, ${RUNNING_ID:-unknown id})"
  if [ -n "${RUNNING_ID:-}" ]; then
    osascript -e "tell application id \"$RUNNING_ID\" to quit" >/dev/null 2>&1
  fi
  for _ in $(seq 1 20); do
    pgrep -f "$ANY_APP" >/dev/null 2>&1 || break
    sleep 1
  done
  pgrep -f "$ANY_APP" >/dev/null 2>&1 \
    && say "WARNING: the old app is still running; the new one will exit on the single-instance lock"
else
  say "app was not running"
fi

if [ "$KEEP_BRAIN" = 1 ]; then
  say "keeping the running brain on :$PORT (--keep-brain)"
else
  say "stopping the dev brain so :$PORT is free for the app's own sidecar"
  bash "$ROOT/scripts/brain.sh" stop >>"$LOG" 2>&1 || true
  for _ in $(seq 1 20); do
    port_busy || break
    sleep 1
  done
  if port_busy; then
    say "WARNING: :$PORT is still held; the app will adopt that listener instead of spawning its own"
  fi
fi

say "launching $APP"
open "$APP" || { say "open failed"; exit 1; }

# Confirm the NEW bundle is the one holding the lock, not a surviving old build.
for _ in $(seq 1 20); do
  pgrep -f "$APP/Contents/MacOS/Undisclosed" >/dev/null 2>&1 && break
  sleep 1
done
if pgrep -f "$APP/Contents/MacOS/Undisclosed" >/dev/null 2>&1; then
  say "new build is running: $(pgrep -f "$APP/Contents/MacOS/Undisclosed" | tr '\n' ' ')"
else
  say "WARNING: $APP is not running after launch (old build still holding the lock?)"
fi

say "waiting for /health on :$PORT"
ANSWER=""
for _ in $(seq 1 60); do
  ANSWER="$(health)"
  [ -n "$ANSWER" ] && break
  sleep 1
done

if [ -n "$ANSWER" ]; then
  say "brain answered: $ANSWER"
  case "$ANSWER" in
    *'"owner":null'*|*'"owner":null,'*)
      say "NOTE: this brain reports no owner, so it is NOT the app's own child."
      say "      A grant given to the app will not cover it."
      ;;
  esac
else
  say "no answer on :$PORT; falling back to the dev brain"
  bash "$ROOT/scripts/brain.sh" start >>"$LOG" 2>&1 || true
fi

say "listener now: $(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $1" pid="$2" "$9}' | tr '\n' ' ')"
say "app process: $(pgrep -f "$APP/Contents/MacOS/Undisclosed" | tr '\n' ' ')"

{
  echo "# desktop toolkit test: what to check next"
  echo
  echo "1. System Settings > Privacy & Security > Accessibility:"
  echo "   enable ${BUNDLE_ID:-the packaged app} (the app that is now running)."
  echo "2. In the agent panel, ask for: desktop_status"
  echo "   Expect the grant to read as present. If it does not, the brain is not"
  echo "   the app's child (check the 'owner' note above) and the grant must go"
  echo "   to whatever hosts the brain instead."
  echo "3. Then: ui_tree with app=\"Finder\""
  echo "   Expect a numbered element list, e.g. 's1e1 AXWindow \"...\"'"
  echo "4. Then: click_element on a harmless element and confirm it reacts."
  echo
  echo "Full log: $LOG"
} >"$VERIFY"
say "wrote $VERIFY"
