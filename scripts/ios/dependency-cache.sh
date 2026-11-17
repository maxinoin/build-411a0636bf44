#!/usr/bin/env bash
set -Eeuo pipefail
# Release assets stay in the private source repository, never in the public Actions cache.
[[ "$(gh api "repos/$PRIVATE_SOURCE_REPOSITORY" --jq '.private')" == true ]] || exit 1
source_dir="$GITHUB_WORKSPACE/private-source/$IOS_PROJECT_DIRECTORY"
key=$( { xcodebuild -version; uname -m; cat "$source_dir/project.yml"; } | shasum -a 256 | cut -c1-24)
tag="ios-dependencies-v1-$key"
archive="$RUNNER_TEMP/ios-dependencies.tar.gz"
if [[ "$1" == restore ]]; then
  mkdir -p "$RUNNER_TEMP/ios-source-packages" "$RUNNER_TEMP/ios-tools"
  if gh release download "$tag" --repo "$PRIVATE_SOURCE_REPOSITORY" --pattern ios-dependencies.tar.gz --dir "$RUNNER_TEMP" >"$RUNNER_TEMP/cache.log" 2>&1; then
    tar -xzf "$archive" -C "$RUNNER_TEMP"
    echo "Private dependency cache restored."
  else
    echo "Private dependency cache miss; resolving normally."
  fi
else
  if gh release view "$tag" --repo "$PRIVATE_SOURCE_REPOSITORY" > /dev/null 2>&1; then exit 0; fi
  mkdir -p "$RUNNER_TEMP/ios-tools"
  if command -v xcodegen >/dev/null; then cp "$(command -v xcodegen)" "$RUNNER_TEMP/ios-tools/xcodegen"; fi
  tar -czf "$archive" -C "$RUNNER_TEMP" ios-source-packages ios-tools
  gh release create "$tag" "$archive" --repo "$PRIVATE_SOURCE_REPOSITORY" \
    --target "$(git -C "$GITHUB_WORKSPACE/private-source" rev-parse HEAD)" \
    --prerelease --latest=false --title 'Private iOS dependency cache' \
    --notes 'Swift dependencies and XcodeGen only. No app source or DerivedData.' >"$RUNNER_TEMP/cache.log" 2>&1
  echo "Private dependency cache saved."
fi
