#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Simon Ugorji
#
# Freshness check: are the BUILT artifacts (and the installed app) behind their
# SOURCE? Catches the "I fixed it but the running app is stale" trap — a frozen
# brain / agent-embed bundle / packaged .app built before your latest edits.
#
#   ./scripts/verify-fresh.sh          # check build outputs + any installed app
#
# Exit code 0 = everything current, 1 = something stale (see the rebuild hints).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
stale=0

# Print the newest source file under $1 that is NEWER than the artifact $2,
# skipping build output / vendored / generated / backup files. Empty = current.
newer_than() {
  local srcdir="$1" artifact="$2"
  find "$srcdir" \
    -type d \( -name node_modules -o -name .venv -o -name __pycache__ \
      -o -name dist -o -name 'dist-*' -o -name lib -o -name generated \
      -o -name .git \) -prune -o \
    -type f ! -name '*.bak' ! -name '*.map' -newer "$artifact" -print 2>/dev/null \
    | head -1
}

# check <label> <artifact> <src-dir> <rebuild-hint>
check() {
  local label="$1" artifact="$2" srcdir="$3" rebuild="$4"
  if [ ! -e "$artifact" ]; then
    printf '  \033[31m✗ %-22s MISSING\033[0m  (%s)\n      build: %s\n' \
      "$label" "${artifact#"$ROOT"/}" "$rebuild"
    stale=1
    return
  fi
  local hit
  hit="$(newer_than "$srcdir" "$artifact")"
  if [ -n "$hit" ]; then
    printf '  \033[31m✗ %-22s STALE\033[0m  (source newer, e.g. %s)\n      rebuild: %s\n' \
      "$label" "${hit#"$ROOT"/}" "$rebuild"
    stale=1
  else
    printf '  \033[32m✓ %-22s up to date\033[0m\n' "$label"
  fi
}

echo "== Build outputs vs source =="
check "frozen brain"        "brain/dist/undisclosed-brain" \
      "brain/app"           "npm run dist:brain"
check "agent-embed bundle"  "packages/undisclosed-agent/assets/agent-embed/agent-embed.umd.js" \
      "agent-ui/src"        "npm run build:agent-ui"
check "undisclosed-agent"   "packages/undisclosed-agent/lib/browser/undisclosed-agent-widget.js" \
      "packages/undisclosed-agent/src" "npm run build --prefix packages/undisclosed-agent"

# Any installed / packaged app: does what it SHIPS match the repo's LATEST build
# outputs? (Content compare, not mtime — copying into the .app resets mtimes, so
# a source-vs-copy mtime check gives false "up to date". If a shipped file
# differs from the repo build output, the app was packaged from an older build.)
check_app_copy() {
  local label="$1" appfile="$2" buildfile="$3"
  if [ ! -e "$appfile" ]; then
    printf '  \033[31m✗ %-20s MISSING in app\033[0m\n' "$label"; stale=1; return
  fi
  if [ ! -e "$buildfile" ]; then
    printf '  \033[33m? %-20s no repo build to compare\033[0m\n' "$label"; return
  fi
  if cmp -s "$appfile" "$buildfile"; then
    printf '  \033[32m✓ %-20s matches current build\033[0m\n' "$label"
  else
    printf '  \033[31m✗ %-20s differs from repo build (stale)\033[0m — repackage + reinstall: npm run dist:mac\n' "$label"
    stale=1
  fi
}

found_app=0
for app in \
  "/Applications/Undisclosed.app" \
  "$ROOT"/apps/desktop/dist/*/Undisclosed.app; do
  [ -d "$app" ] || continue
  found_app=1
  echo
  echo "== Installed app: $app (shipped vs repo build) =="
  check_app_copy "app brain" \
    "$app/Contents/Resources/brain/undisclosed-brain" \
    "brain/dist/undisclosed-brain"
  check_app_copy "app agent bundle" \
    "$app/Contents/Resources/app/node_modules/undisclosed-agent/assets/agent-embed/agent-embed.umd.js" \
    "packages/undisclosed-agent/assets/agent-embed/agent-embed.umd.js"
done
[ "$found_app" -eq 0 ] && { echo; echo "  (no installed/packaged .app found — skipping app check)"; }

echo
if [ "$stale" -ne 0 ]; then
  echo "⚠️  Something is STALE — the running app may not have your latest changes."
  echo "    Fast dev loop:  ./scripts/dev.sh rebuild   (brain + agent-ui + Theia :3000)"
  echo "    Full package:   npm run dist:mac           (then reinstall the .app)"
  exit 1
fi
echo "✅ All build artifacts are current."
