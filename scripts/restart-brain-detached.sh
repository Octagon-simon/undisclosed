#!/usr/bin/env bash
# Detached brain restart + verify, with a "noup" heads-up note.
#
# WHY DETACHED: the agent session lives INSIDE the brain process (its shell is a
# child of the brain), so killing the brain ends the session that asked for the
# restart. Run this via nohup/setsid so it OUTLIVES the brain: it waits for the
# agent's final message to land, restarts the brain, then records a verdict and
# a "what to check next" list.
#
# PROTOCOL (per user request, 2026-10-13; hardened the same day). Every restart,
# in order, ALL steps done by THIS script so a restart can never go silent even
# if the agent session dies:
#   1. create a "noup" heads-up note            -> under noup/
#   2. send the user a message (notify-user.sh) -> macOS notification + ntfy push
#   3. wait a few seconds so the message lands  -> --delay, default 15s
#   4. restart the brain
#   5. tell the user what to check next         -> --check into the verify log
#
# Step 2 used to be "the agent sends the user a message". That depended on the
# agent session outliving the restart, and it repeatedly did not: the message was
# never delivered. The script now OWNS the message (scripts/notify-user.sh), so
# the heads-up lands independently of the agent session.
#
# USAGE:
#   nohup ./scripts/restart-brain-detached.sh \
#       --reason "picked up trigger_controller scope change" \
#       --check  "reload the editor, open Triggers, confirm Attach-to shows" \
#       >/dev/null 2>&1 &
#
#   Add --dry-run to rehearse the message + noup WITHOUT restarting the brain.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="/tmp/brain-restart-verify.log"
NOUP_DIR="$ROOT/noup"
DELAY=15
REASON="(no reason given)"
CHECK="(none specified)"
DRY_RUN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --reason)  REASON="${2:-}"; shift 2;;
    --check)   CHECK="${2:-}";  shift 2;;
    --delay)   DELAY="${2:-15}"; shift 2;;
    --dry-run) DRY_RUN=1; shift;;
    *) shift;;
  esac
done

TS="$(date '+%Y-%m-%d %H:%M:%S')"
STAMP="$(date '+%Y%m%d_%H%M%S')"
mkdir -p "$NOUP_DIR"
NOUP="$NOUP_DIR/${STAMP}-restart.md"
{
  echo "# Restart noup - $TS"
  echo
  echo "**Reason:** $REASON"
  echo
  echo "**What to check next:**"
  echo
  echo "$CHECK"
  echo
} > "$NOUP"

# --- Step 2: send the user the heads-up message BEFORE the brain goes down. ---
# This is the step that must never be skipped, so it runs itself here (not left
# to the agent), and its result is written into the verify log below.
MSG="Restarting the brain in ${DELAY}s. Reason: ${REASON}"
[ "$CHECK" != "(none specified)" ] && MSG="$MSG | Next: ${CHECK}"
NOTIFY="$ROOT/scripts/notify-user.sh"
if [ -f "$NOTIFY" ]; then
  notify_out="$(bash "$NOTIFY" \
    --title "Undisclosed" \
    --subtitle "Brain restarting" \
    --message "$MSG" 2>&1 || echo "notify-user exited non-zero")"
else
  notify_out="notify-user.sh not found at $NOTIFY"
fi

exec >>"$OUT" 2>&1
echo "==================================================================="
echo "detached brain restart requested: $TS"
echo "reason: $REASON"
echo "noup:   $NOUP"
echo "message sent to user: $MSG"
echo "notify-user result:   $notify_out"
echo "waiting ${DELAY}s so the message lands before the brain restarts..."
sleep "$DELAY"

if [ "$DRY_RUN" = 1 ]; then
  echo "DRY RUN: message + noup done; NOT restarting. Would run: ./scripts/brain.sh restart"
  echo "restart+verify finished (dry run): $(date '+%Y-%m-%d %H:%M:%S')"
  echo "==================================================================="
  exit 0
fi

cd "$ROOT" || { echo "FATAL: cannot cd $ROOT"; exit 1; }
echo "--- running: ./scripts/brain.sh restart ---"
./scripts/brain.sh restart || echo "restart command returned non-zero (see .brain.log)"

echo "waiting up to 40s for the new brain to come up on :5001..."
up=no
for i in $(seq 1 40); do
  if lsof -nP -iTCP:5001 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "brain is listening on :5001 (after ${i}s)"; up=yes; break
  fi
  sleep 1
done
[ "$up" = yes ] || echo "brain did NOT come up in 40s"

echo "giving Slack Socket Mode up to 30s to connect..."
sleep 30

echo "--- verification (from $ROOT/.brain.log) ---"
grep -q "Slack Socket Mode listener started" "$ROOT/.brain.log" \
  && echo "VERDICT listener started ......... YES" \
  || echo "VERDICT listener started ......... (string not found)"
grep -q "slack socket mode connecting" "$ROOT/.brain.log" \
  && echo "VERDICT connection attempted ..... YES" \
  || echo "VERDICT connection attempted ..... (string not found)"
grep -qiE "new session .* has been established" "$ROOT/.brain.log" \
  && echo "VERDICT socket session established  YES" \
  || echo "VERDICT socket session established  (not yet / check .brain.log)"
echo "--- last relevant brain.log lines ---"
grep -iE "slack|socket|\[brain\]|Uvicorn running|Application startup" "$ROOT/.brain.log" | tail -30
echo "--- WHAT TO CHECK NEXT ---"
echo "$CHECK"
echo "restart+verify finished: $(date '+%Y-%m-%d %H:%M:%S')"
echo "==================================================================="
