#!/usr/bin/env bash
set -Eeuo pipefail
if ! command -v gh >/dev/null 2>&1; then
  if ! brew install --quiet gh >/dev/null 2>&1; then
    echo "::error title=Private upload failed::Could not install GitHub CLI; installer output was suppressed."
    exit 1
  fi
fi

# Never deliver an IPA to a public repository, even if the secret is misconfigured.
if ! destination_private="$(gh api "repos/$PRIVATE_SOURCE_REPOSITORY" --jq '.private' \
  2>"$RUNNER_TEMP/private-visibility-check.log")" || [[ "$destination_private" != "true" ]]; then
  echo "::error title=Private delivery blocked::The destination could not be verified as private."
  exit 1
fi

test_result="${SIMULATOR_TEST_RESULT:-skipped}"
test_failed="false"
if [[ "$test_result" == failure ]]; then test_failed="true"; fi
if [[ "$test_failed" == "true" && "${ALLOW_FAILED_UI_TESTS_FOR_PRIVATE_CANDIDATE:-false}" != "true" ]]; then
  echo "::error title=Private candidate blocked::Failed simulator tests require the explicit candidate-build option."
  exit 1
fi

release_tag="ios-build-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
app_variant="${APP_VARIANT:-dev}"
case "$app_variant" in
  dev)
    variant_label="KnightRoute Dev"
    simulation_note="Developer simulated-bus controls: enabled; the app starts on local sample data and uses localhost if switched to live service."
    ;;
  production)
    variant_label="KnightRoute Production"
    simulation_note="Developer simulated-bus controls: disabled; the app uses the configured live transit service."
    ;;
  *) echo "::error title=Private upload failed::Unknown app variant."; exit 1 ;;
esac
sheet_style="${SHEET_STYLE:-colored-divider-only}"
case "$sheet_style" in
  accent-rail-gray-divider) style_label="accent rail + gray divider" ;;
  colored-divider-only) style_label="colored divider only" ;;
  *) echo "::error title=Private upload failed::Unknown route sheet style."; exit 1 ;;
esac
release_title="${variant_label} unsigned iOS build ${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT} — ${style_label}"
if [[ "$test_failed" == "true" ]]; then
  release_title="${release_title} — TESTS FAILED CANDIDATE"
fi
if ! gh release create "$release_tag" \
  "$RUNNER_TEMP/app-unsigned.ipa" \
  --repo "$PRIVATE_SOURCE_REPOSITORY" \
  --target "$(git -C "$GITHUB_WORKSPACE/private-source" rev-parse HEAD)" \
  --latest=false \
  --title "$release_title" \
  --notes "Unsigned iPhone IPA built from the selected private revision by the public build broker. App variant: ${variant_label}. ${simulation_note} Route sheet style: ${style_label}. Simulator UI tests for this revision: ${test_result}." \
  --prerelease >"$RUNNER_TEMP/private-release-upload.log" 2>&1; then
  echo "::error title=Private upload failed::The IPA could not be uploaded to a private release; response details were suppressed."
  exit 1
fi

echo "The unsigned IPA is available in a private prerelease in the private source repository."
