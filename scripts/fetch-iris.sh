#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Simon Ugorji
#
# Fetch the pinned `iris` screenshot binary (github.com/brijr/iris, MIT) into
# resources/binaries/iris/<os>-<arch>/, where the brain's Page Screenshots
# toolkit and electron-builder both expect it.
#
#   ./scripts/fetch-iris.sh                  # host platform, best effort
#   ./scripts/fetch-iris.sh darwin-x64       # explicit target (CI matrix)
#   ./scripts/fetch-iris.sh --check          # exit 0 only if present at the pin
#   ./scripts/fetch-iris.sh --required       # exit 1 if the fetch fails
#
# Best effort is the default so `npm install` and `npm run setup` never fail
# without a network. Packaging passes --required so a release cannot ship
# without the binary.
#
# iris ships macOS (arm64/x64) and Linux (x64 musl) only. Windows exits 0
# without a binary, and the capability is simply not registered there.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="0.4.1"
BASE_URL="https://github.com/brijr/iris/releases/download/v${VERSION}"

host_target() {
  local os arch
  os="$(uname -s | tr '[:upper:]' '[:lower:]')"
  case "$(uname -m)" in
    arm64|aarch64) arch="arm64" ;;
    x86_64|amd64) arch="x86_64" ;;
    *) arch="$(uname -m)" ;;
  esac
  echo "${os}-${arch}"
}

asset_for() {
  case "$1" in
    darwin-arm64) echo "iris-aarch64-apple-darwin.tar.gz" ;;
    darwin-x86_64|darwin-x64) echo "iris-x86_64-apple-darwin.tar.gz" ;;
    linux-x86_64|linux-x64) echo "iris-x86_64-unknown-linux-musl.tar.gz" ;;
    *) echo "" ;;
  esac
}

CHECK_ONLY=0
REQUIRED=0
TARGET_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --check) CHECK_ONLY=1 ;;
    --required) REQUIRED=1 ;;
    --*) echo "[fetch-iris] unknown flag: $1" >&2; exit 2 ;;
    *) TARGET_ARG="$1" ;;
  esac
  shift
done

TARGET="${TARGET_ARG:-$(host_target)}"
case "$TARGET" in
  darwin-x64) TARGET=darwin-x86_64 ;;
  linux-x64) TARGET=linux-x86_64 ;;
esac
ASSET="$(asset_for "$TARGET")"

fail() {
  if [ "$REQUIRED" -eq 1 ]; then
    echo "[fetch-iris] ERROR: $*" >&2
    exit 1
  fi
  echo "[fetch-iris] WARNING: $*" >&2
  echo "[fetch-iris] Page Screenshots stays off until you rerun: npm run fetch:iris" >&2
  exit 0
}

if [ -z "$ASSET" ]; then
  echo "[fetch-iris] no prebuilt binary for ${TARGET}; skipping (feature stays off)."
  exit 0
fi

DEST_DIR="$ROOT/resources/binaries/iris/$TARGET"
DEST="$DEST_DIR/iris"

if [ -x "$DEST" ] && "$DEST" --version 2>/dev/null | grep -q "$VERSION"; then
  echo "[fetch-iris] already at v$VERSION: $DEST"
  exit 0
fi
if [ "$CHECK_ONLY" -eq 1 ]; then
  echo "[fetch-iris] missing or stale: $DEST" >&2
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "[fetch-iris] downloading v$VERSION ($TARGET)"
if ! curl -fsSL --retry 3 --retry-delay 2 -o "$TMP/$ASSET" "$BASE_URL/$ASSET"; then
  fail "download failed: $BASE_URL/$ASSET"
fi

tar -xzf "$TMP/$ASSET" -C "$TMP"
mkdir -p "$DEST_DIR"
BIN="$(find "$TMP" -type f -name iris -perm -u+x | head -n 1)"
if [ -z "$BIN" ]; then
  BIN="$(find "$TMP" -type f -name iris | head -n 1)"
fi
if [ -z "$BIN" ]; then
  fail "archive did not contain an iris binary"
fi

if ! "$BIN" --version 2>/dev/null | grep -q "$VERSION"; then
  fail "downloaded binary is not v$VERSION"
fi
install -m 0755 "$BIN" "$DEST"
echo "[fetch-iris] installed $DEST"
