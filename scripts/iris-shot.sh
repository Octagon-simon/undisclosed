#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Simon Ugorji
#
# Dev wrapper around the bundled iris binary, so the agent (or you) can grab a
# page shot without going through the brain:
#
#   npm run shot -- http://localhost:3000
#   npm run shot -- --selector '#hero' --padding 24 http://localhost:3000
#
# Puts the output in .screenshots/ unless you pass your own -o.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
case "$(uname -m)" in
  arm64|aarch64) ARCH="arm64" ;;
  x86_64|amd64) ARCH="x86_64" ;;
  *) ARCH="$(uname -m)" ;;
esac

BIN="${IRIS_BIN:-$ROOT/resources/binaries/iris/${OS}-${ARCH}/iris}"
if [ ! -x "$BIN" ]; then
  echo "[iris-shot] no binary at $BIN" >&2
  echo "[iris-shot] run: ./scripts/fetch-iris.sh" >&2
  exit 1
fi

args=("$@")
has_out=0
for a in "${args[@]}"; do
  case "$a" in -o|--out) has_out=1 ;; esac
done
if [ "$has_out" -eq 0 ]; then
  args=(-o "$ROOT/.screenshots/" "${args[@]}")
fi

exec "$BIN" "${args[@]}"
