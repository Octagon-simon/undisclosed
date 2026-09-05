#!/bin/bash
# Freeze the Python brain into a single self-contained executable so installers
# don't require Python on the user's machine. Output: brain/dist/undisclosed-brain
# (electron-builder picks it up via extraResources — see docs/PACKAGING.md).
#
# Uses the brain's own venv (provisioned by uv from pyproject.toml). Used by CI
# (release.yml) and runnable locally to test the freeze.
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/brain/.venv"

# Provision the venv if it's missing (fresh checkout / CI). scripts/brain.sh
# setup runs `uv sync` from brain/pyproject.toml.
if [ ! -x "$VENV/bin/python" ]; then
  echo "==> brain/.venv missing — provisioning (scripts/brain.sh setup)…"
  bash "$ROOT/scripts/brain.sh" setup
fi

PY="$VENV/bin/python"
cd "$ROOT/brain"

echo "==> Installing PyInstaller into the brain venv…"
"$PY" -m pip install --quiet pyinstaller

echo "==> Freezing brain → dist/undisclosed-brain…"
# --collect-all pulls in CAMEL + our app package data. Add --hidden-import as
# the build surfaces missing modules (toolkits, playwright, etc.).
"$PY" -m PyInstaller --noconfirm --onefile --name undisclosed-brain \
  --collect-all camel \
  --collect-all app \
  main.py

echo "==> Done: $(ls -lh dist/undisclosed-brain* 2>/dev/null | awk '{print $5, $NF}')"
