#!/usr/bin/env bash
# Create a release: decide the version, make sure CHANGELOG.md has a section for it,
# tag it and publish a GitHub release with that section as the release notes.
# Usage: tools/release.sh [patch|minor|major|current]
#   current  release the version already in manifest.json (used on push)
#   others   bump manifest.json from the latest v* tag (first release: current version)
set -euo pipefail
mode="${1:-current}"
manifest=custom_components/cozify_hub_dev/manifest.json
cur=$(jq -r .version "$manifest")
last=$(git describe --tags --abbrev=0 --match 'v*' 2>/dev/null || true)

if [ "$mode" = current ] || [ -z "$last" ]; then
  new="$cur"
else
  IFS=. read -r ma mi pa <<<"${last#v}"
  case "$mode" in
    major) new="$((ma + 1)).0.0" ;;
    minor) new="$ma.$((mi + 1)).0" ;;
    patch) new="$ma.$mi.$((pa + 1))" ;;
    *) echo "unknown mode $mode" >&2; exit 2 ;;
  esac
fi
tag="v$new"
if git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
  echo "Tag $tag already exists - nothing to release."
  exit 0
fi

changed=0
if [ "$new" != "$cur" ]; then
  tmp=$(mktemp)
  jq --arg v "$new" '.version = $v' "$manifest" >"$tmp" && mv "$tmp" "$manifest"
  changed=1
fi

# Changelog section for this version (auto-generated from commit subjects if missing).
if ! grep -q "^## $new " CHANGELOG.md; then
  range="${last:+$last..}HEAD"
  {
    echo "## $new - dev channel"
    git log "$range" --no-merges --pretty='* %s' --invert-grep --grep='^Release v' || true
    echo
  } >new_section.md
  { head -n 2 CHANGELOG.md; cat new_section.md; tail -n +3 CHANGELOG.md; } >CHANGELOG.new
  mv CHANGELOG.new CHANGELOG.md
  rm new_section.md
  changed=1
fi
awk -v h="## $new " '/^## /{f=(index($0, h)==1)} f && !/^## /' CHANGELOG.md >notes.md
[ -s notes.md ] || echo "Release $tag" >notes.md

if [ "$changed" = 1 ]; then
  git config user.name "github-actions[bot]"
  git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
  git add "$manifest" CHANGELOG.md
  git commit -m "Release $tag"
  git push origin HEAD
fi
gh release create "$tag" --target "$(git rev-parse HEAD)" --title "$tag" --notes-file notes.md
rm -f notes.md
echo "Released $tag"
