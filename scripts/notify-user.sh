#!/usr/bin/env bash
# notify-user.sh - send a heads-up MESSAGE to the user, out-of-band.
#
# WHY THIS EXISTS
# ---------------
# The agent's chat message is delivered BY the brain's agent session. When that
# same session is about to restart the brain, the session can die before the
# message is flushed, so the restart went silent (this happened repeatedly on
# 2026-10-13). A detached script cannot post into the chat, but it CAN reach the
# user the same way their other coding agents do: a signed macOS notification and
# an ntfy phone push. This script is that channel, so "tell the user" no longer
# depends on the agent session surviving the restart.
#
# CHANNELS (best-effort; more than one may fire so it is hard to miss):
#   1. Beckoned native macOS notifier (real sender identity, not Script Editor)
#   2. ntfy push to the topic in ~/.beckoned/config.json (the user's phone)
#   3. terminal-notifier
#   4. osascript display notification
#
# USAGE
#   scripts/notify-user.sh --title "Undisclosed" --subtitle "Brain restarting" \
#       --message "reason ... | next: reload the editor"
#   echo "the message" | scripts/notify-user.sh --title "Undisclosed"
#
# Exits 0 if at least one channel accepted the message, 1 if none did, 2 if no
# message was supplied. Never blocks the caller for long (each channel is capped).
set -u

TITLE="Undisclosed"
SUBTITLE=""
MESSAGE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --title)    TITLE="${2:-}";    shift 2;;
    --subtitle) SUBTITLE="${2:-}"; shift 2;;
    --message)  MESSAGE="${2:-}";  shift 2;;
    *) shift;;
  esac
done

# Fall back to stdin when no --message was given.
if [ -z "$MESSAGE" ] && [ ! -t 0 ]; then
  MESSAGE="$(cat)"
fi

if [ -z "${MESSAGE// /}" ]; then
  echo "notify-user: no message supplied (use --message or stdin)" >&2
  exit 2
fi

BECKON_HOME="$HOME/.beckoned"
sent=0

# 1) Beckoned native notifier. The binary lives under opt/native in current
#    builds; opt/dist/native is the older location. Try both.
for NB in \
  "$BECKON_HOME/opt/native/Beckoned.app/Contents/MacOS/beckoned-notifier" \
  "$BECKON_HOME/opt/dist/native/Beckoned.app/Contents/MacOS/beckoned-notifier"; do
  if [ -x "$NB" ]; then
    if "$NB" -title "$TITLE" -subtitle "$SUBTITLE" -message "$MESSAGE" >/dev/null 2>&1; then
      sent=1
    fi
    break
  fi
done

# 2) ntfy push (the user's phone), topic from the beckoned config. Opt-in: no
#    topic configured means this is a no-op, matching beckoned's own behavior.
if command -v node >/dev/null 2>&1 && [ -f "$BECKON_HOME/config.json" ]; then
  CFG="$(node -e 'try{const c=require(process.env.HOME+"/.beckoned/config.json");process.stdout.write((c.ntfyTopic||"")+"\t"+(c.ntfyServer||"https://ntfy.sh"))}catch(e){}' 2>/dev/null)"
  TOPIC="${CFG%%$'\t'*}"
  SERVER="${CFG#*$'\t'}"
  if [ -n "$TOPIC" ]; then
    SERVER="${SERVER%/}"
    BODY="$MESSAGE"
    [ -n "$SUBTITLE" ] && BODY="$SUBTITLE - $MESSAGE"
    if curl -s -m 5 -H "Title: $TITLE" -H "Priority: high" \
        --data-binary "$BODY" "$SERVER/$TOPIC" >/dev/null 2>&1; then
      sent=1
    fi
  fi
fi

# 3) terminal-notifier, if the user has it.
if command -v terminal-notifier >/dev/null 2>&1; then
  if terminal-notifier -title "$TITLE" -subtitle "$SUBTITLE" -message "$MESSAGE" \
      -group undisclosed-restart >/dev/null 2>&1; then
    sent=1
  fi
fi

# 4) osascript display notification, the last resort (no auth, always present).
if command -v osascript >/dev/null 2>&1; then
  # Escape backslashes and double quotes for AppleScript string literals.
  esc() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }
  if osascript -e "display notification \"$(esc "$MESSAGE")\" with title \"$(esc "$TITLE")\" subtitle \"$(esc "$SUBTITLE")\"" >/dev/null 2>&1; then
    sent=1
  fi
fi

if [ "$sent" = 1 ]; then
  echo "notify-user: message delivered"
else
  echo "notify-user: no channel delivered the message" >&2
  exit 1
fi
