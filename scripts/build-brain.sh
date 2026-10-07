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

# The venv layout is OS-dependent: Linux/macOS put the interpreter at
# bin/python, Windows (including Git Bash on windows-latest) at
# Scripts/python.exe. Resolve whichever exists — don't hardcode bin/python,
# which made the Windows CI run die with "No such file or directory".
venv_python() {
  if [ -x "$VENV/bin/python" ]; then
    printf '%s' "$VENV/bin/python"
  elif [ -x "$VENV/Scripts/python.exe" ]; then
    printf '%s' "$VENV/Scripts/python.exe"
  fi
}

# Provision the venv if it's missing (fresh checkout / CI). scripts/brain.sh
# setup runs `uv sync` from brain/pyproject.toml.
PY="$(venv_python)"
if [ -z "$PY" ]; then
  echo "==> brain/.venv missing — provisioning (scripts/brain.sh setup)…"
  bash "$ROOT/scripts/brain.sh" setup
  PY="$(venv_python)"
fi

if [ -z "$PY" ]; then
  echo "ERROR: brain/.venv has no interpreter after provisioning ($VENV)" >&2
  exit 1
fi

cd "$ROOT/brain"

echo "==> Installing PyInstaller into the brain venv…"
# Use the venv's pip when it has one (local dev). A freshly `uv sync`-created venv
# may not ship pip, so fall back to `uv pip` (uv is what provisioned the venv).
if ! "$PY" -m pip install --quiet pyinstaller 2>/dev/null; then
  echo "==> venv has no pip; installing PyInstaller via uv…"
  uv pip install --python "$PY" pyinstaller
fi

echo "==> Freezing brain → dist/undisclosed-brain…"
# --collect-all pulls in CAMEL + our app package data. Add --hidden-import as
# the build surfaces missing modules (toolkits, playwright, etc.).
# --collect-all github bundles PyGithub, which the GitHub toolkit imports
# lazily (camel's @dependencies_required('github')), so static analysis misses
# it and the frozen sidecar would crash when GITHUB_ACCESS_TOKEN is set.
"$PY" -m PyInstaller --noconfirm --onefile --name undisclosed-brain \
  --collect-all camel \
  --collect-all app \
  --collect-all github \
  main.py

echo "==> Done: $(ls -lh dist/undisclosed-brain* 2>/dev/null | awk '{print $5, $NF}')"
