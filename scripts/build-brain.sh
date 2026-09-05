#!/bin/bash
# Freeze the Python brain into a single self-contained executable so installers
# don't require Python on the user's machine. Output: brain/dist/undisclosed-brain
# (electron-builder picks it up via extraResources — see docs/PACKAGING.md).
#
# Used by CI (release.yml) and can be run locally to test the freeze.
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/brain"

PY="${PYTHON:-python3}"

echo "==> Installing brain deps + PyInstaller…"
"$PY" -m pip install --upgrade pip
[ -f requirements.txt ] && "$PY" -m pip install -r requirements.txt
"$PY" -m pip install pyinstaller

echo "==> Freezing brain → dist/undisclosed-brain…"
# --collect-all pulls in CAMEL + our app package data. Add --hidden-import as
# the build surfaces missing modules (toolkits, playwright, etc.).
"$PY" -m PyInstaller --noconfirm --onefile --name undisclosed-brain \
  --collect-all camel \
  --collect-all app \
  main.py

echo "==> Done: $(ls -lh dist/undisclosed-brain 2>/dev/null | awk '{print $5, $NF}')"
