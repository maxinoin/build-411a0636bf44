#!/usr/bin/env bash
set -Eeuo pipefail
if [[ -n "$REQUESTED_REVISION" ]]; then
  if [[ ! "$REQUESTED_REVISION" =~ ^[0-9a-f]{40}$ ]]; then
    echo "::error title=Invalid private revision::Use a full lowercase commit SHA."
    exit 1
  fi
  revision="$REQUESTED_REVISION"
else
  response="$(curl --silent --show-error --fail \
    -H "Accept: application/vnd.github+json" \
    -H "Authorization: Bearer $PRIVATE_SOURCE_READ_TOKEN" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    --get --data-urlencode 'sha=codex/ipa-queue' --data-urlencode 'per_page=1' \
    "https://api.github.com/repos/$PRIVATE_SOURCE_REPOSITORY/commits")"
  revision="$(jq -er '.[0].sha' <<< "$response")"
  if [[ ! "$revision" =~ ^[0-9a-f]{40}$ ]]; then
    echo "::error title=Queue revision unavailable::The private IPA queue branch has no valid commit."
    exit 1
  fi
fi

echo "revision=$revision" >> "$GITHUB_OUTPUT"
echo "should_build=true" >> "$GITHUB_OUTPUT"
echo "Resolved the source revision for the manually requested IPA build."
