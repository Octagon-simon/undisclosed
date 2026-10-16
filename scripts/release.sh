#!/bin/bash
# Usage:
#   npm run release [patch|minor|major]           # stable release (unchanged)
#   npm run release [patch|minor|major] <preid>   # pre-release, e.g. `minor beta` -> 0.1.0-beta.0
#   npm run release prerelease <preid>            # next pre-release, e.g. beta.0 -> beta.1
#   npm run release beta                          # sugar: preminor beta the first time, then
#                                                 # step the existing beta (beta.0 -> beta.1)
#
# Bumps the version, commits, tags, and pushes — CI (.github/workflows/release.yml)
# then builds the installers on native runners and publishes them to a Release.
# No manual version editing. Mirrors the pulpit-ai release flow, adapted for this
# npm + Theia + Python-brain repo.
#
# A PRE-RELEASE tag (any version carrying a `-`, e.g. v0.1.0-beta.0) is published
# by CI as a GitHub **pre-release**: it gets the "Pre-release" badge and is never
# promoted to "latest", so it does not reach users tracking stable/main. The
# version bump is committed on the CURRENT branch only, so `main` is untouched.
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BUMP=${1:-patch}
PREID=${2:-}

# `beta` / `rc` sugar: choose the bump from the current version so repeat runs
# step the pre-release number (0.1.0-beta.0 -> 0.1.0-beta.1) instead of recomputing
# it from scratch.
if [[ "$BUMP" == "beta" || "$BUMP" == "rc" ]]; then
  PREID="$BUMP"
  if [ -f "apps/desktop/package.json" ]; then
    CUR="$(node -p "require('./apps/desktop/package.json').version")"
  else
    CUR="$(node -p "require('./package.json').version")"
  fi
  if [[ "$CUR" == *-"$PREID".* ]]; then
    BUMP=prerelease
  else
    BUMP=preminor
  fi
fi

# With a preid, promote a plain bump to its pre* form — npm ignores --preid for a
# plain `patch`/`minor`/`major`.
if [[ -n "$PREID" ]]; then
  case "$BUMP" in
    patch) BUMP=prepatch ;;
    minor) BUMP=preminor ;;
    major) BUMP=premajor ;;
  esac
fi

if [[ ! "$BUMP" =~ ^(patch|minor|major|prepatch|preminor|premajor|prerelease)$ ]]; then
  echo "Usage: npm run release [patch|minor|major|prepatch|preminor|premajor|prerelease] [preid]"
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

VERSION_ARGS=("$BUMP")
if [[ -n "$PREID" ]]; then
  VERSION_ARGS+=(--preid "$PREID")
fi

# Bump the desktop app version if it exists (electron-builder reads it for the
# installer name + auto-update feed), then sync the repo root to match. Fall back
# to bumping just the root until apps/desktop exists (see docs/PACKAGING.md).
if [ -f "apps/desktop/package.json" ]; then
  ( cd apps/desktop && npm version "${VERSION_ARGS[@]}" --no-git-tag-version >/dev/null )
  VERSION=$(node -p "require('./apps/desktop/package.json').version")
  npm version "$VERSION" --no-git-tag-version --allow-same-version >/dev/null
else
  VERSION=$(npm version "${VERSION_ARGS[@]}" --no-git-tag-version)
  VERSION=${VERSION#v}
fi

if [[ "$VERSION" == *-* ]]; then
  COMMIT_MSG="chore: pre-release v${VERSION}"
else
  COMMIT_MSG="chore: release v${VERSION}"
fi

git add .
git commit -m "$COMMIT_MSG"
git tag "v${VERSION}"

BRANCH=$(git rev-parse --abbrev-ref HEAD)
git push origin "$BRANCH"
git push origin "v${VERSION}"

echo ""
if [[ "$VERSION" == *-* ]]; then
  echo "Pre-released v${VERSION} — CI builds installers and attaches them to a"
  echo "GitHub PRE-release (never promoted to \"latest\"). Watch the Actions tab."
else
  echo "Released v${VERSION} — CI builds installers and attaches them to the Release."
  echo "Watch the Actions tab."
fi
