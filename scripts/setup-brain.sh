#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Simon Ugorji
#
# Provision the eigent-theia-owned Python venv for the agent brain.
# Uses uv to create brain/.venv and install deps from brain/pyproject.toml +
# uv.lock. Run once (and after dependency bumps). Makes eigent-theia
# self-sufficient — no dependency on the eigent app having provisioned a venv.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRAIN="$ROOT/brain"

if ! command -v uv >/dev/null 2>&1; then
  echo "[setup-brain] 'uv' not found. Install it: https://docs.astral.sh/uv/" >&2
  exit 1
fi

if [ ! -f "$BRAIN/pyproject.toml" ]; then
  echo "[setup-brain] $BRAIN/pyproject.toml missing — is the brain vendored?" >&2
  exit 1
fi

echo "[setup-brain] provisioning venv at $BRAIN/.venv (uv sync)…"
cd "$BRAIN"
# uv reads .python-version (3.11) and fetches it if absent; installs from uv.lock.
uv sync
echo "[setup-brain] done. venv: $BRAIN/.venv"
