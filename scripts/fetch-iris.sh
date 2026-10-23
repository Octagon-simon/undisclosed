#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Simon Ugorji
#
# Fetch the pinned `iris` screenshot binary (github.com/brijr/iris, MIT) into
# resources/binaries/iris/<os>-<arch>/, where the brain's Page Screenshots
# toolkit and electron-builder both expect it.
#
#   ./scripts/fetch-iris.sh                  # host platform
#   ./scripts/fetch-iris.sh darwin-x64       # explicit target (CI matrix)
#   ./scripts/fetch-iris.sh --check          # exit 0 if present at the pin
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
    darwin-x86_64) echo "iris-x86_64-apple-darwin.tar.gz" ;;
    linux-x86_64) echo "iris-x86_64-unknown-linux-musl.tar.gz" ;;
    *) echo "" ;;
  esac
}

CHECK_ONLY=0
if [ "${1:-}" = "--check" ]; then
  CHECK_ONLY=1
  shift
fi

TARGET="${1:-$(host_target)}"
ASSET="$(asset_for "$TARGET")"

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
  echo "[fetch-iris] download failed: $BASE_URL/$ASSET" >&2
  exit 1
fi

tar -xzf "$TMP/$ASSET" -C "$TMP"
mkdir -p "$DEST_DIR"
BIN="$(find "$TMP" -type f -name iris -perm -u+x | head -n 1)"
if [ -z "$BIN" ]; then
  BIN="$(find "$TMP" -type f -name iris | head -n 1)"
fi
if [ -z "$BIN" ]; then
  echo "[fetch-iris] archive did not contain an iris binary" >&2
  exit 1
fi

install -m 0755 "$BIN" "$DEST"
if ! "$DEST" --version 2>/dev/null | grep -q "$VERSION"; then
  echo "[fetch-iris] downloaded binary is not v$VERSION" >&2
  exit 1
fi
echo "[fetch-iris] installed $DEST"
