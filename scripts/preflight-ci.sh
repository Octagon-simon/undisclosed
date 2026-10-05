#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Simon Ugorji
#
# Local preflight: run the critical bits of .github/workflows/release.yml HERE,
# on this machine, so a broken lockfile / plugin download / build fails before you
# push a tag (and burn a CI run).
#
#   ./scripts/preflight-ci.sh              # fast: env + syntax + lock-sync checks
#   ./scripts/preflight-ci.sh --full       # real install + rebuild + build
#   ./scripts/preflight-ci.sh --full --package   # also package (electron-builder --dir)
#
# It mirrors CI but runs the HOST platform only. It cannot see Windows/Linux-only
# problems — run --full on those OSes (or in a container) if you suspect one.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FULL=0
PACKAGE=0
for arg in "$@"; do
  case "$arg" in
    --full) FULL=1 ;;
    --package) FULL=1; PACKAGE=1 ;;
    -h | --help)
      sed -n '2,15p' "$0"
      exit 0
      ;;
    *)
      echo "unknown flag: $arg (try --help)" >&2
      exit 2
      ;;
  esac
done

fail=0
step() { echo; echo "=== $* ==="; }
# run <label> <cmd...>
run() {
  local label="$1"
  shift
  step "$label"
  if "$@"; then
    echo "  [ok] $label"
  else
    echo "  [FAIL] $label" >&2
    fail=1
  fi
}
# run_in <dir> <label> <cmd...>
run_in() {
  local dir="$1" label="$2"
  shift 2
  run "$label" bash -c 'cd "$1" && shift && "$@"' _ "$dir" "$@"
}

step "environment"
echo "  os:   $(uname -s) $(uname -m)"
echo "  node: $(node -v)  npm: $(npm -v)"
# CI pins Node 20; Theia's native builds are known to break on newer Node.
node -e 'const maj=+process.versions.node.split(".")[0]; if(maj<18||maj>20){console.warn("  ! node "+process.versions.node+" is outside engines (>=18 <=20); CI builds on 20")}'

step "workflow / manifest syntax"
if bash -n scripts/*.sh 2>/dev/null; then
  echo "  [ok] shell scripts parse"
else
  echo "  [FAIL] shell syntax error (run: bash -n scripts/<file>.sh)" >&2
  fail=1
fi
for f in package.json apps/desktop/package.json packages/*/package.json; do
  if node -e "JSON.parse(require('fs').readFileSync(process.argv[1],'utf8'))" "$f"; then
    echo "  [ok] $f"
  else
    echo "  [FAIL] invalid JSON: $f" >&2
    fail=1
  fi
done
if node -e "require.resolve('js-yaml')" >/dev/null 2>&1; then
  if node -e "const y=require('js-yaml'),fs=require('fs'); y.load(fs.readFileSync('.github/workflows/release.yml','utf8'))"; then
    echo "  [ok] .github/workflows/release.yml"
  else
    echo "  [FAIL] invalid YAML: .github/workflows/release.yml" >&2
    fail=1
  fi
else
  echo "  [skip] js-yaml unavailable — YAML not validated"
fi

# Lock-sync is exactly what broke CI before ("Missing: X from lock file"). npm ci
# --dry-run runs that check without touching node_modules.
run "root lock sync (npm ci --dry-run)" npm ci --dry-run
run "desktop lock resolve (npm install --dry-run)" bash -c 'cd apps/desktop && npm install --dry-run'

if [ "$FULL" = 1 ]; then
  echo
  echo "############ FULL preflight: real install + build (this mutates node_modules) ############"
  run "root npm ci" npm ci
  run_in "apps/desktop" "desktop npm install" npm install
  run_in "apps/desktop" "rebuild native modules for Electron" npm run rebuild
  run "download VS Code plugins (bounded)" bash "$ROOT/scripts/ci-download-plugins.sh"
  run_in "apps/desktop" "build Theia app" npm run build
  if [ "$PACKAGE" = 1 ]; then
    run_in "apps/desktop" "package (electron-builder --dir)" npm run package:dir
  fi
else
  echo
  echo "(fast mode: skipped real install/build — re-run with --full to mirror CI end to end)"
fi

echo
if [ "$fail" = 1 ]; then
  echo "preflight FAILED — fix the [FAIL] items above before pushing a tag."
  exit 1
fi
echo "preflight OK."
