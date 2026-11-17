#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "$(gh api "repos/$PRIVATE_SOURCE_REPOSITORY" --jq '.private' 2>/dev/null)" != "true" ]]; then
  echo "::error title=Private delivery blocked::The destination could not be verified as private."
  exit 1
fi
tag="ios-visual-audit-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
# Deliver the log before packaging optional test bundles.
if ! gh release create "$tag" "$RUNNER_TEMP/xcode-test.log" \
  --repo "$PRIVATE_SOURCE_REPOSITORY" \
  --target "$(git -C "$GITHUB_WORKSPACE/private-source" rev-parse HEAD)" \
  --latest=false --prerelease --title "Private simulator visual audit" \
  --notes "Private simulator screenshots and test diagnostics." \
  >"$RUNNER_TEMP/private-visual-upload.log" 2>&1; then
  echo "::error::Private release creation failed."
  sed -E 's#https?://[^ ]+#[URL]#g' "$RUNNER_TEMP/private-visual-upload.log" | tail -n 4
  exit 1
fi
if compgen -G "$RUNNER_TEMP/live-route-captures/*.png" >/dev/null; then
  ditto -c -k --keepParent "$RUNNER_TEMP/live-route-captures" "$RUNNER_TEMP/live-route-captures.zip"
  gh release upload "$tag" "$RUNNER_TEMP/live-route-captures.zip" \
    --repo "$PRIVATE_SOURCE_REPOSITORY" >>"$RUNNER_TEMP/private-visual-upload.log" 2>&1
fi
if [[ -d "$RUNNER_TEMP/ios-ui-tests.xcresult" ]]; then
  mkdir -p "$RUNNER_TEMP/sheet-attachments"
  if xcrun xcresulttool export attachments --path "$RUNNER_TEMP/ios-ui-tests.xcresult" --output-path "$RUNNER_TEMP/sheet-attachments" >"$RUNNER_TEMP/sheet-export.log" 2>&1; then
    ditto -c -k --keepParent "$RUNNER_TEMP/sheet-attachments" "$RUNNER_TEMP/sheet-screenshots.zip"
    gh release upload "$tag" "$RUNNER_TEMP/sheet-screenshots.zip" --repo "$PRIVATE_SOURCE_REPOSITORY" >>"$RUNNER_TEMP/private-visual-upload.log" 2>&1
  fi
fi
echo "Simulator results uploaded privately."
