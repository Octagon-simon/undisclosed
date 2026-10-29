#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Simon Ugorji
#
# Produce a Developer ID signed copy of the packaged macOS app, so TCC grants
# (Accessibility, Screen Recording) survive rebuilds. An ad-hoc bundle pins the
# grant to its cdhash, and `npm run package:dir` produces a new cdhash every
# time, so the grant silently stops matching.
#
#   ./scripts/sign-app.sh                          # dist -> dist-signed, then sign
#   ./scripts/sign-app.sh path/to/Undisclosed.app  # sign that bundle in place
#
# The app must be quit: signing a bundle that is running leaves the live process
# holding an old signature while new helper processes read the new one, which
# makes Chromium refuse to spawn them.
#
# Local installs only. A Developer ID issued to another team must never sign a
# distributed build; see docs/PACKAGING.md.
#
#   UNDISCLOSED_CODESIGN_IDENTITY   identity to sign with (default: the first
#                                   "Developer ID Application" in the keychain)
#   UNDISCLOSED_CODESIGN_TIMESTAMP  --timestamp (secure, needs network) instead
#                                   of the default --timestamp=none
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT/apps/desktop/dist/mac-arm64/Undisclosed.app"
INSTALLED="$ROOT/apps/desktop/dist-signed/mac-arm64/Undisclosed.app"
APP="$INSTALLED"
COPY=0
if [ "$#" -gt 0 ]; then APP="$1"; else COPY=1; fi

IDENTITY="${UNDISCLOSED_CODESIGN_IDENTITY:-}"
ENTITLEMENTS="${UNDISCLOSED_ENTITLEMENTS:-$ROOT/apps/desktop/build/entitlements.mac.plist}"
TIMESTAMP="${UNDISCLOSED_CODESIGN_TIMESTAMP:---timestamp=none}"

say() { printf '  %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

if [ -z "$IDENTITY" ]; then
  IDENTITY="$(security find-identity -v -p codesigning 2>/dev/null |
    awk -F'"' '/Developer ID Application/ {print $2; exit}')"
fi
[ -n "$IDENTITY" ] ||
  die "no Developer ID Application identity in the keychain; set UNDISCLOSED_CODESIGN_IDENTITY"
[ -f "$ENTITLEMENTS" ] || die "no entitlements at $ENTITLEMENTS"
security find-identity -v -p codesigning | grep -qF "$IDENTITY" ||
  die "identity is not in the keychain: $IDENTITY"

if [ "$COPY" = 1 ]; then
  [ -d "$SOURCE" ] || die "no packaged app at $SOURCE (run: npm run package:dir)"
  say "copying dist/mac-arm64/Undisclosed.app into dist-signed"
  mkdir -p "$(dirname "$INSTALLED")"
  ditto "$SOURCE" "$INSTALLED"
fi
[ -d "$APP" ] || die "no app bundle at $APP"

plist="$APP/Contents/Info.plist"
executable="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$plist" 2>/dev/null || true)"
[ -n "$executable" ] || die "cannot read CFBundleExecutable from $plist"
if pgrep -f "$APP/Contents/MacOS/$executable" >/dev/null 2>&1; then
  die "$(basename "$APP") is running; quit it first"
fi

sign() {
  codesign --force "$TIMESTAMP" --options runtime --sign "$IDENTITY" "$@"
}

say "signing loose Mach-O code in Contents/Frameworks"
while IFS= read -r -d '' file; do
  sign "$file" >/dev/null 2>&1 || die "failed to sign $file"
done < <(find "$APP/Contents/Frameworks" -type f -not -path '*.app/*' \
  \( -perm -u+x -o -name '*.dylib' -o -name '*.so' -o -name '*.node' \) -print0 |
  while IFS= read -r -d '' f; do
    if file -b "$f" | grep -q 'Mach-O'; then printf '%s\0' "$f"; fi
  done)

say "signing frameworks"
while IFS= read -r -d '' framework; do
  sign "$framework" >/dev/null 2>&1 || die "failed to sign $framework"
done < <(find "$APP/Contents/Frameworks" -maxdepth 1 -type d -name '*.framework' -print0)

say "signing helper apps"
while IFS= read -r -d '' helper; do
  sign --entitlements "$ENTITLEMENTS" "$helper" >/dev/null 2>&1 || die "failed to sign $helper"
done < <(find "$APP/Contents/Frameworks" -maxdepth 1 -type d -name '*.app' -print0)

say "signing $(basename "$APP")"
sign --entitlements "$ENTITLEMENTS" "$APP"

say "verifying"
codesign --verify --deep --strict --verbose=2 "$APP" 2>&1 | sed 's/^/    /' || die "verify failed"

info="$(codesign -dv --verbose=4 "$APP" 2>&1)"
identifier="$(printf '%s\n' "$info" | awk -F= '/^Identifier=/{print $2}')"
team="$(printf '%s\n' "$info" | awk -F= '/^TeamIdentifier=/{print $2}')"
authority="$(printf '%s\n' "$info" | awk -F= '/^Authority=/{print $2; exit}')"
cdhash="$(printf '%s\n' "$info" | awk -F= '/^CDHash=/{print $2; exit}')"
say "identifier $identifier"
say "team       ${team:-not set}"
say "authority  ${authority:-unknown}"
say "cdhash     ${cdhash:-unknown}"
[ "$identifier" = "dev.octagon.undisclosed" ] ||
  say "note: identifier is not dev.octagon.undisclosed, TCC will key on '$identifier'"
say ""
say "grant Accessibility to this bundle:"
say "${APP#$ROOT/}"
