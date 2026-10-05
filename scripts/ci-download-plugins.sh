#!/usr/bin/env bash
# Download the pinned VS Code extensions into apps/desktop/plugins — bounded and
# cache-friendly.
#
# Why this exists: `theia download:plugins` resolves extension packs / extension
# dependencies over the network with NO socket timeout, so a stalled connection
# hangs forever. On the Intel macOS CI runner it printed
#   --- collecting extension-packs ---
#   --- collecting extension dependencies ---
# and then hung for 1h30m+ with no progress. This wrapper:
#   * hard-caps every attempt with scripts/with-timeout.mjs (default 10 min),
#   * retries a few times,
#   * skips the network entirely when plugins are already present (cache hit),
#   * verifies the core pinned plugins actually landed before declaring success.
#
# Knobs: CI_PLUGINS_TIMEOUT (seconds per attempt), CI_PLUGINS_ATTEMPTS.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESKTOP="$ROOT/apps/desktop"
PLUGINS_DIR="$DESKTOP/plugins"
SENTINEL="$PLUGINS_DIR/.download-complete"
PER_ATTEMPT_SECS="${CI_PLUGINS_TIMEOUT:-600}"
ATTEMPTS="${CI_PLUGINS_ATTEMPTS:-3}"

# Core (pinned) plugin ids come straight from package.json's theiaPlugins map.
core_plugins() {
  node -e "const p=require(process.argv[1]); process.stdout.write(Object.keys(p.theiaPlugins||{}).join('\n'))" \
    "$DESKTOP/package.json"
}

# Print (one per line) any pinned plugin whose directory is missing.
missing_plugins() {
  local id
  while IFS= read -r id; do
    [ -n "$id" ] || continue
    [ -d "$PLUGINS_DIR/$id" ] || printf '%s\n' "$id"
  done < <(core_plugins)
}

verify() {
  local missing
  missing="$(missing_plugins)"
  if [ -n "$missing" ]; then
    echo "!! missing plugin dirs:" >&2
    printf '%s\n' "$missing" | sed 's/^/     - /' >&2
    return 1
  fi
  return 0
}

# Cache hit: the sentinel is committed to the action cache alongside the plugins.
if [ -f "$SENTINEL" ] && verify; then
  echo "==> plugins present ($PLUGINS_DIR) — skipping download (cache hit)"
  exit 0
fi

mkdir -p "$PLUGINS_DIR"
cd "$DESKTOP"

for attempt in $(seq 1 "$ATTEMPTS"); do
  echo "==> download:plugins attempt $attempt/$ATTEMPTS (timeout ${PER_ATTEMPT_SECS}s)"
  # --ignore-errors: an unresolvable *optional* extension must not fail the build.
  # We verify the pinned core set below, which is what the app actually ships.
  if node "$ROOT/scripts/with-timeout.mjs" "$PER_ATTEMPT_SECS" \
      npm run download:plugins -- --ignore-errors; then
    if verify; then
      touch "$SENTINEL"
      echo "==> plugins downloaded and verified"
      exit 0
    fi
    echo "!! attempt $attempt exited 0 but core plugins are missing; retrying" >&2
  else
    echo "!! attempt $attempt failed or timed out; retrying" >&2
  fi
done

# Last chance: everything may be on disk even if a later resolution errored.
if verify; then
  touch "$SENTINEL"
  echo "==> plugins present despite download errors — continuing"
  exit 0
fi

echo "ERROR: could not download the pinned VS Code plugins after $ATTEMPTS attempts" >&2
exit 1
