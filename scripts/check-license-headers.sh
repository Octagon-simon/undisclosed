#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Simon Ugorji
#
# Fail if a source file in the areas this repo actively changes has no license
# header, if a file added since the base ref is missing the Simon Ugorji
# attribution line, or if a file listed in simon-owned-files.txt carries the
# Eigent banner.
#
#   ./scripts/check-license-headers.sh              # base: origin/main
#   ./scripts/check-license-headers.sh HEAD~10      # explicit base
#
# Header forms accepted (must be in the first 4 lines):
#   Copyright 2025-2026 @ Eigent.ai All Rights Reserved.
#   Copyright (c) 2026 Simon Ugorji
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BASE="${1:-origin/main}"
fail=0

files=()
while IFS= read -r f; do
  files+=("$f")
done < <(
  find brain/app brain/tests agent-ui/src \
    \( -name '*.py' -o -name '*.ts' -o -name '*.tsx' \) -type f
)

if [ "${#files[@]}" -eq 0 ]; then
  echo "license headers: no files found (wrong cwd?)" >&2
  exit 1
fi

for f in "${files[@]}"; do
  if ! head -4 "$f" | grep -qE 'Copyright.*(Eigent\.ai|Simon Ugorji)'; then
    echo "missing license header: $f" >&2
    fail=1
  fi
done

# New files carry both banners. Existing/upstream files only need their own.
if git rev-parse --verify --quiet "$BASE" >/dev/null; then
  while IFS= read -r f; do
    [ -f "$f" ] || continue
    case "$f" in
      brain/app/*|brain/tests/*|agent-ui/src/*) ;;
      *) continue ;;
    esac
    case "$f" in
      *.py|*.ts|*.tsx) ;;
      *) continue ;;
    esac
    if ! head -15 "$f" | grep -q 'Simon Ugorji'; then
      echo "new file missing Simon Ugorji attribution: $f" >&2
      fail=1
    fi
    if head -4 "$f" | grep -q 'Eigent\.ai'; then
      echo "new file uses the Eigent banner; new files carry Simon Ugorji: $f" >&2
      fail=1
    fi
  done < <(git diff --name-only --diff-filter=A "$BASE"...HEAD; git ls-files --others --exclude-standard)
else
  echo "license headers: base ref '$BASE' not found, skipping new-file attribution check"
fi

# Files this repo owns outright are listed in simon-owned-files.txt. They must
# carry the Simon banner only; the new-file check misses them once committed.
OWNERS="$ROOT/scripts/simon-owned-files.txt"
if [ -f "$OWNERS" ]; then
  while IFS= read -r f; do
    case "$f" in ''|'#'*) continue ;; esac
    [ -f "$f" ] || continue
    if ! head -4 "$f" | grep -q 'Simon Ugorji'; then
      echo "owned file missing Simon attribution: $f" >&2
      fail=1
    fi
    if head -4 "$f" | grep -q 'Eigent\.ai'; then
      echo "owned file uses the Eigent banner: $f" >&2
      fail=1
    fi
  done < "$OWNERS"
fi

if [ "$fail" -eq 1 ]; then
  echo "license header check FAILED" >&2
  exit 1
fi
echo "license headers OK (${#files[@]} files)"
