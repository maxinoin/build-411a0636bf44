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

app_variant="${APP_VARIANT:-dev}"
case "$app_variant" in
  dev) ;;
  production)
    release_tag="${PRODUCTION_RELEASE_TAG:-}"
    if [[ ! "$release_tag" =~ ^[-A-Za-z0-9._]+$ ]]; then
      echo "::error title=Production build requires a release::Choose a published, non-prerelease source release tag."
      exit 1
    fi
    release_response="$(curl --silent --show-error --fail \
      -H "Accept: application/vnd.github+json" \
      -H "Authorization: Bearer $PRIVATE_SOURCE_READ_TOKEN" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com/repos/$PRIVATE_SOURCE_REPOSITORY/releases/tags/$release_tag")" || {
        echo "::error title=Production release unavailable::The selected source tag is not a published release."
        exit 1
      }
    if ! jq -e '.draft == false and .prerelease == false' >/dev/null <<< "$release_response"; then
      echo "::error title=Production release invalid::Production IPAs require a published, non-prerelease source release."
      exit 1
    fi
    tagged_revision="$(curl --silent --show-error --fail \
      -H "Accept: application/vnd.github+json" \
      -H "Authorization: Bearer $PRIVATE_SOURCE_READ_TOKEN" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com/repos/$PRIVATE_SOURCE_REPOSITORY/commits/$release_tag" | jq -er '.sha')" || {
        echo "::error title=Production source unavailable::Could not resolve the source release tag to a commit."
        exit 1
      }
    if [[ "$tagged_revision" != "$revision" ]]; then
      echo "::error title=Production source mismatch::The selected commit does not match the published release tag."
      exit 1
    fi
    ;;
  *)
    echo "::error title=Build configuration invalid::Choose app_variant dev or production."
    exit 1
    ;;
esac

echo "revision=$revision" >> "$GITHUB_OUTPUT"
echo "should_build=true" >> "$GITHUB_OUTPUT"
echo "Resolved the source revision for the requested IPA build."
