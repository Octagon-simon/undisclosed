#!/usr/bin/env bash
# Download the pinned VS Code extensions into apps/desktop/plugins.
#
# Bounded, cache-friendly, and NETWORK-FREE when the plugins are already there.
#
# Why this exists (and why it does not just run download:plugins regardless):
#
#   `theia download:plugins` always walks the plugin dir and resolves extension
#   packs / extension dependencies, and its requests have no socket timeout, so a
#   stalled connection hangs forever. On the Intel macOS runner it printed:
#       --- collecting extension-packs ---
#       --- collecting extension dependencies ---
#   and then sat there; the step was only stopped by our hard cap (603s on run
#   37363700981, with the plugins already restored from cache in 2s).
#
#   The "already downloaded - skipping" lines only skip the .vsix FETCH. They do
#   NOT stop the resolution pass and they do NOT stop the process from hanging.
#   So the only way to not burn CI minutes is to not invoke the tool when the
#   pinned plugins are already on disk. That is the fast path below.
#
# A plugin counts as present only when its id exists AND the installed manifest
# version equals the version pinned in its URL, so a stale cache fails
# verification and triggers a real download.
#
# Knobs: CI_PLUGINS_TIMEOUT (seconds per attempt, default 240),
#        CI_PLUGINS_ATTEMPTS  (default 3).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESKTOP="$ROOT/apps/desktop"
PLUGINS_DIR="$DESKTOP/plugins"
SENTINEL="$PLUGINS_DIR/.download-complete"
PER_ATTEMPT_SECS="${CI_PLUGINS_TIMEOUT:-240}"
ATTEMPTS="${CI_PLUGINS_ATTEMPTS:-3}"

# Emit "id<TAB>version" for every pinned plugin. The version is the path segment
# before /file/ in the open-vsx URL, e.g.
#   https://open-vsx.org/api/esbenp/prettier-vscode/11.0.3/file/... -> 11.0.3
pinned_plugins() {
  node -e '
    const p = require(process.argv[1]);
    for (const [id, url] of Object.entries(p.theiaPlugins || {})) {
      const m = String(url).match(/\/([^/]+)\/file\//);
      process.stdout.write(id + "\t" + (m ? m[1] : "") + "\n");
    }
  ' "$DESKTOP/package.json"
}

# Echo the path to a plugin's manifest inside the unpacked vsix, if any.
manifest_of() {
  local id="$1"
  if [ -f "$PLUGINS_DIR/$id/extension/package.json" ]; then
    printf '%s\n' "$PLUGINS_DIR/$id/extension/package.json"; return 0
  fi
  if [ -f "$PLUGINS_DIR/$id/package.json" ]; then
    printf '%s\n' "$PLUGINS_DIR/$id/package.json"; return 0
  fi
  return 1
}

# Print (one per line) every pinned plugin that is missing or at the wrong version.
missing_plugins() {
  local id expected manifest installed
  while IFS=$'\t' read -r id expected; do
    [ -n "$id" ] || continue
    if ! manifest="$(manifest_of "$id")"; then
      printf '%s (missing)\n' "$id"; continue
    fi
    installed="$(node -e 'try{process.stdout.write(String(require(process.argv[1]).version||""))}catch(e){}' "$manifest")"
    if [ -n "$expected" ] && [ "$installed" != "$expected" ]; then
      printf '%s (have %s, want %s)\n' "$id" "${installed:-?}" "$expected"
    fi
  done < <(pinned_plugins)
}

verify() {
  local missing
  missing="$(missing_plugins)"
  if [ -n "$missing" ]; then
    echo "!! pinned plugins not ready:" >&2
    printf '%s\n' "$missing" | sed 's/^/     - /' >&2
    return 1
  fi
  return 0
}

# Print pinned ids whose directory exists but is incomplete or at the wrong
# version. `theia download:plugins` SKIPS any existing plugin dir, so such a dir
# would never be refreshed — it has to be removed first.
stale_plugin_ids() {
  local id expected manifest installed
  while IFS=$'\t' read -r id expected; do
    [ -n "$id" ] || continue
    [ -d "$PLUGINS_DIR/$id" ] || continue
    if ! manifest="$(manifest_of "$id")"; then
      printf '%s\n' "$id"; continue
    fi
    installed="$(node -e 'try{process.stdout.write(String(require(process.argv[1]).version||""))}catch(e){}' "$manifest")"
    if [ -n "$expected" ] && [ "$installed" != "$expected" ]; then
      printf '%s\n' "$id"
    fi
  done < <(pinned_plugins)
}

# Fast path: everything is already present and at the pinned version. Never touch
# the network. This keeps warm CI runs (cache restored) at a couple of seconds
# instead of waiting out the hang the tool is prone to.
if verify >/dev/null 2>&1; then
  mkdir -p "$PLUGINS_DIR"
  touch "$SENTINEL"
  echo "==> pinned VS Code plugins already present and at the pinned versions"
  echo "    ($PLUGINS_DIR) — skipping download (no network)"
  exit 0
fi

mkdir -p "$PLUGINS_DIR"

# A restored cache, or a mid-download kill, can leave a plugin dir that exists
# but is stale (old pin) or incomplete. `theia download:plugins` skips existing
# dirs, so prune those first or they would never be re-fetched.
stale="$(stale_plugin_ids)"
if [ -n "$stale" ]; then
  echo "==> removing stale/incomplete plugin dirs so they get re-fetched"
  while IFS= read -r id; do
    [ -n "$id" ] || continue
    echo "   - $id"
    rm -rf "$PLUGINS_DIR/$id"
  done <<< "$stale"
fi

cd "$DESKTOP"

for attempt in $(seq 1 "$ATTEMPTS"); do
  echo "==> download:plugins attempt $attempt/$ATTEMPTS (hard cap ${PER_ATTEMPT_SECS}s)"
  # --ignore-errors: an unresolvable *optional* extension must not fail the build.
  # We verify the pinned core set below, which is what the app actually ships.
  node "$ROOT/scripts/with-timeout.mjs" "$PER_ATTEMPT_SECS" \
    npm run download:plugins -- --ignore-errors &
  tool=$!

  # The tool frequently finishes the download and then hangs on exit (its requests
  # have no socket timeout). Watch the plugins dir: once every pinned plugin
  # verifies twice in a row, stop the tool instead of waiting out the cap. The
  # hard cap in with-timeout.mjs remains the backstop if this never succeeds.
  stable=0
  while kill -0 "$tool" 2>/dev/null; do
    if verify >/dev/null 2>&1; then
      stable=$((stable + 1))
      if [ "$stable" -ge 2 ]; then
        kill -TERM "$tool" 2>/dev/null || true
        break
      fi
    else
      stable=0
    fi
    sleep 3
  done
  wait "$tool" 2>/dev/null || true

  # The download may have completed even though the command was killed, so verify
  # regardless of the exit code instead of paying for another full attempt.
  if verify; then
    touch "$SENTINEL"
    echo "==> plugins downloaded and verified"
    exit 0
  fi
  echo "!! attempt $attempt incomplete; retrying" >&2
done

echo "ERROR: could not materialise the pinned VS Code plugins after $ATTEMPTS attempts" >&2
exit 1
