#!/usr/bin/env bash
# Publish a GitHub Release from a directory of assets, one file at a time.
#
#   scripts/publish-release-assets.sh v1.2.3 release-assets
#
# Why not softprops/action-gh-release: it uploads the whole file list in
# parallel, and when a same-named asset already exists (a re-run of a failed
# job) it PATCHes that asset, which GitHub answers with 404 while the previous
# upload is still processing ("Not Found - ...#update-a-release-asset"). We
# upload sequentially with --clobber, which deletes the old asset first, and
# retry each file on its own so a transient failure does not re-upload a 500 MB
# installer.
#
# The release is created as a DRAFT and published only after every asset landed,
# so a failed run never leaves a public release that is missing installers.
# Assets already uploaded at the same size are skipped, which makes a re-run
# pick up where the failed one stopped. Tags with a semver pre-release suffix
# (-beta.0, -rc.1, ...) are published as a GitHub pre-release, which GitHub
# never marks "latest".
set -euo pipefail

TAG="${1:?usage: publish-release-assets.sh <tag> <assets-dir>}"
DIR="${2:?usage: publish-release-assets.sh <tag> <assets-dir>}"
ATTEMPTS="${ATTEMPTS:-5}"

[[ -d "$DIR" ]] || { echo "no such directory: $DIR" >&2; exit 1; }
: "${GH_TOKEN:?GH_TOKEN is required}"

IS_PRE=0
if [[ "$TAG" == *-* ]]; then IS_PRE=1; fi

if ! gh release view "$TAG" >/dev/null 2>&1; then
  echo "==> creating draft release $TAG"
  create=(--draft --title "$TAG" --generate-notes)
  if (( IS_PRE )); then create+=(--prerelease); fi
  gh release create "$TAG" "${create[@]}"
fi

# name<TAB>size of what is already on the release.
remote="$(gh release view "$TAG" --json assets -q '.assets[] | "\(.name)\t\(.size)"' || true)"
remote_size() {
  printf '%s\n' "$remote" | awk -F'\t' -v name="$1" '$1 == name { print $2; exit }'
}
file_size() {
  stat -c%s "$1" 2>/dev/null || stat -f%z "$1"
}

files=()
while IFS= read -r -d '' f; do files+=("$f"); done \
  < <(find "$DIR" -type f -print0 | sort -z)
(( ${#files[@]} > 0 )) || { echo "no assets in $DIR" >&2; exit 1; }

echo "==> uploading ${#files[@]} assets to $TAG"
for file in "${files[@]}"; do
  name="$(basename "$file")"
  size="$(file_size "$file")"
  if [[ "$(remote_size "$name")" == "$size" ]]; then
    echo "  [skip] $name (already uploaded, $size bytes)"
    continue
  fi
  attempt=1
  while :; do
    if gh release upload "$TAG" "$file" --clobber >/dev/null; then
      echo "  [ok] $name"
      break
    fi
    if (( attempt >= ATTEMPTS )); then
      echo "  [FAIL] $name after $ATTEMPTS attempts" >&2
      exit 1
    fi
    delay=$(( attempt * 5 ))
    echo "  retrying $name in ${delay}s (attempt $attempt/$ATTEMPTS failed)" >&2
    sleep "$delay"
    attempt=$(( attempt + 1 ))
  done
done

if [[ "$(gh release view "$TAG" --json isDraft -q .isDraft)" == "true" ]]; then
  echo "==> publishing $TAG"
  edit=(--draft=false)
  if (( IS_PRE )); then edit+=(--prerelease); fi
  gh release edit "$TAG" "${edit[@]}"
fi

echo "==> $TAG is published with $(gh release view "$TAG" --json assets -q '.assets | length') assets"
