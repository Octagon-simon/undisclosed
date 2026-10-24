#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Simon Ugorji
#
# Enforce attribution on the areas this repo changes:
#   - every source file carries a copyright header in its first 4 lines
#   - a file we created carries Simon's copyright as line 1, no Portions line
#   - a pre-existing file that already had a copyright header keeps line 1 and
#     gets "Portions Copyright 2026 Simon Ugorji. All Rights Reserved." as line 2
#   - a pre-existing file with no copyright header gets Simon's banner
#   - files in simon-owned-files.txt carry the Simon banner only
#   - no file repeats the Simon attribution
#
#   ./scripts/check-license-headers.sh              # base: origin/main
#   ./scripts/check-license-headers.sh HEAD~10      # explicit base
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

BASE="${1:-origin/main}"
fail=0

fail_msg() {
  echo "$*" >&2
  fail=1
}

in_scope() {
  case "$1" in
    brain/app/* | brain/tests/* | agent-ui/src/*) return 0 ;;
  esac
  return 1
}

is_src() {
  case "$1" in
    *.py | *.ts | *.tsx) return 0 ;;
  esac
  return 1
}

# Files this repo owns outright: Simon banner only, never the Eigent banner.
OWNERS="$ROOT/scripts/simon-owned-files.txt"
owned=()
if [ -f "$OWNERS" ]; then
  while IFS= read -r line; do
    case "$line" in '' | '#'*) continue ;; esac
    owned+=("${line#./}")
  done <"$OWNERS"
fi

is_owned() {
  local f="$1" o
  for o in "${owned[@]:-}"; do
    [ "$f" = "$o" ] && return 0
  done
  return 1
}

new_files=()
mod_files=()
if git rev-parse --verify --quiet "$BASE" >/dev/null; then
  while IFS= read -r f; do
    [ -n "$f" ] && new_files+=("$f")
  done < <(git diff --name-only --diff-filter=A "$BASE"...HEAD; git ls-files --others --exclude-standard)
  while IFS= read -r f; do
    [ -n "$f" ] && mod_files+=("$f")
  done < <(git diff --name-only --diff-filter=M "$BASE"...HEAD; git diff --name-only --diff-filter=M HEAD)
else
  echo "license headers: base ref '$BASE' not found, skipping changed-file attribution checks" >&2
fi

is_in() {
  local needle="$1" item
  shift
  for item in "$@"; do
    [ "$item" = "$needle" ] && return 0
  done
  return 1
}

# 1. Every source file in the managed trees has some copyright header.
count=0
while IFS= read -r f; do
  count=$((count + 1))
  if ! head -4 "$f" | grep -qE 'Copyright.*(Eigent\.ai|Simon Ugorji)'; then
    fail_msg "missing license header: $f"
  fi
  # 2. The Portions line must not be repeated (a pasted header usually duplicates
  #    it). Banner framing legitimately repeats the copyright twice, so only the
  #    Portions line is counted here.
  dup=$(head -20 "$f" | grep -c 'Portions Copyright.*Simon Ugorji')
  if [ "$dup" -gt 1 ]; then
    fail_msg "duplicate Simon Ugorji attribution ($dup lines): $f"
  fi
done < <(find brain/app brain/tests agent-ui/src \
  \( -name '*.py' -o -name '*.ts' -o -name '*.tsx' \) -type f)

if [ "$count" -eq 0 ]; then
  echo "license headers: no files found (wrong cwd?)" >&2
  exit 1
fi

# The Portions line belongs directly under the copyright line it qualifies, so a
# header that dropped it into the middle of the block is still wrong.
portions_after_copyright() {
  local f="$1" n
  n=$(grep -n 'Portions Copyright.*Simon Ugorji' "$f" 2>/dev/null | head -1 | cut -d: -f1)
  [ -n "$n" ] || return 1
  [ "$n" -le 4 ] || return 1
  sed -n "$((n - 1))p" "$f" | grep -q 'Copyright'
}

# Who held the copyright before this work: eigent | simon | other | none.
# Falls back to the current file when the base ref or the path is missing.
base_copyright_holder() {
  local f="$1" line
  if git rev-parse --verify --quiet "$BASE:$f" >/dev/null 2>&1; then
    line=$(git show "$BASE:$f" | head -4 | grep 'Copyright' | head -1)
  else
    line=$(head -4 "$f" | grep 'Copyright' | head -1)
  fi
  if [ -z "$line" ]; then
    echo none
  elif printf '%s' "$line" | grep -q 'Eigent\.ai'; then
    echo eigent
  elif printf '%s' "$line" | grep -q 'Simon Ugorji'; then
    echo simon
  else
    echo other
  fi
}

# 3. A file we created carries Simon's copyright as the main header line, no
#    Portions line, and never the upstream banner.
for f in "${new_files[@]:-}"; do
  [ -n "$f" ] || continue
  [ -f "$f" ] || continue
  in_scope "$f" || continue
  is_src "$f" || continue
  if head -4 "$f" | grep -q 'Eigent\.ai'; then
    fail_msg "new file uses the Eigent banner (line 1 must be Simon's copyright): $f"
  fi
  if head -4 "$f" | grep -q 'Portions Copyright'; then
    fail_msg "new file carries a Portions line (created files get the banner only): $f"
  fi
  if ! head -4 "$f" | grep -q 'Copyright.*Simon Ugorji'; then
    fail_msg "new file missing Simon Ugorji copyright header: $f"
  fi
done

# 4. A modified upstream file keeps line 1 and says which parts are Simon's. If
#    it had no copyright header to begin with, it gets the Simon banner instead
#    of a Portions line, because there is nothing to attach the line to.
for f in "${mod_files[@]:-}"; do
  [ -n "$f" ] || continue
  [ -f "$f" ] || continue
  in_scope "$f" || continue
  is_src "$f" || continue
  is_in "$f" "${new_files[@]:-}" && continue
  is_owned "$f" && continue
  case "$(base_copyright_holder "$f")" in
    eigent | other)
      portions_after_copyright "$f" ||
        fail_msg "modified file missing 'Portions Copyright 2026 Simon Ugorji. All Rights Reserved.' as line 2: $f"
      ;;
    none)
      if head -4 "$f" | grep -q 'Portions Copyright'; then
        fail_msg "headerless file got a Portions line (it needs Simon's banner as line 1): $f"
      elif ! head -4 "$f" | grep -q 'Copyright.*Simon Ugorji'; then
        fail_msg "headerless file missing Simon Ugorji copyright header: $f"
      fi
      ;;
    simon)
      if head -4 "$f" | grep -q 'Portions Copyright'; then
        fail_msg "Simon-authored file carries a Portions line (banner only): $f"
      fi
      ;;
  esac
done

# 5. Simon-owned files carry that banner only.
for f in "${owned[@]:-}"; do
  [ -n "$f" ] || continue
  [ -f "$f" ] || continue
  if ! head -4 "$f" | grep -q 'Simon Ugorji'; then
    fail_msg "owned file missing Simon attribution: $f"
  fi
  if head -4 "$f" | grep -q 'Eigent\.ai'; then
    fail_msg "owned file uses the Eigent banner: $f"
  fi
  if head -4 "$f" | grep -q 'Portions Copyright'; then
    fail_msg "owned file carries a Portions line (banner only): $f"
  fi
done

# 6. Changed scripts are Simon's too.
for f in "${new_files[@]:-}" "${mod_files[@]:-}"; do
  [ -n "$f" ] || continue
  [ -f "$f" ] || continue
  case "$f" in
    scripts/*.sh | scripts/*.mjs | scripts/*.py) ;;
    *) continue ;;
  esac
  if ! head -4 "$f" | grep -q 'Simon Ugorji'; then
    fail_msg "changed script missing Simon attribution: $f"
  fi
done

if [ "$fail" -eq 1 ]; then
  echo "license header check FAILED" >&2
  exit 1
fi
echo "license headers OK ($count files)"
