#!/bin/bash
# Usage: npm run release [patch|minor|major]
#
# Bumps the version, commits, tags, and pushes — CI (.github/workflows/release.yml)
# then builds the installers on native runners and publishes them to a Release.
# No manual version editing. Mirrors the pulpit-ai release flow, adapted for this
# npm + Theia + Python-brain repo.
set -e

BUMP=${1:-patch}
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! "$BUMP" =~ ^(patch|minor|major)$ ]]; then
  echo "Usage: npm run release [patch|minor|major]"
  exit 1
fi

# Clean tree required — a bump/tag on top of uncommitted work is a mess.
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Working tree has uncommitted changes. Commit or stash them first."
  exit 1
fi

# Gate BEFORE bumping so a failed build never leaves a dangling version bump.
# (Keep this fast; the heavy per-OS packaging happens in CI.)
echo "==> Building the agent bundle (gate)…"
npm run build:agent-ui

# Bump the desktop app version if it exists (electron-builder reads it for the
# installer name + auto-update feed), then sync the repo root to match. Fall back
# to bumping just the root until apps/desktop exists (see docs/PACKAGING.md).
if [ -f "apps/desktop/package.json" ]; then
  ( cd apps/desktop && npm version "$BUMP" --no-git-tag-version >/dev/null )
  VERSION=$(node -p "require('./apps/desktop/package.json').version")
  npm version "$VERSION" --no-git-tag-version --allow-same-version >/dev/null
else
  VERSION=$(npm version "$BUMP" --no-git-tag-version)
  VERSION=${VERSION#v}
fi

git add .
git commit -m "chore: release v${VERSION}"
git tag "v${VERSION}"

BRANCH=$(git rev-parse --abbrev-ref HEAD)
git push origin "$BRANCH"
git push origin "v${VERSION}"

echo ""
echo "Released v${VERSION} — CI builds installers and attaches them to the Release."
echo "Watch the Actions tab."
