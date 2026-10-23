#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Simon Ugorji
#
# Enforce attribution on the areas this repo changes:
#   - every source file carries a copyright header in its first 4 lines
#   - new files name Simon Ugorji within the first 15 lines
#   - modified upstream files carry a "Portions Copyright ... Simon Ugorji" line
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

# 3. New files must name Simon. Both banners are fine: the Eigent block comes
#    from the neighbouring file, the Portions line marks the new authorship.
for f in "${new_files[@]:-}"; do
  [ -n "$f" ] || continue
  [ -f "$f" ] || continue
  in_scope "$f" || continue
  is_src "$f" || continue
  if ! head -15 "$f" | grep -q 'Simon Ugorji'; then
    fail_msg "new file missing Simon Ugorji attribution: $f"
  fi
done

# 4. Modified upstream files must say which parts are Simon's. This is the check
#    that catches a forgotten Portions line on an existing file.
for f in "${mod_files[@]:-}"; do
  [ -n "$f" ] || continue
  [ -f "$f" ] || continue
  in_scope "$f" || continue
  is_src "$f" || continue
  is_in "$f" "${new_files[@]:-}" && continue
  is_owned "$f" && continue
  if ! head -4 "$f" | grep -q 'Portions Copyright.*Simon Ugorji'; then
    fail_msg "modified file missing 'Portions Copyright ... Simon Ugorji': $f"
  fi
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
