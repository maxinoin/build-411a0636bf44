#!/usr/bin/env bash
set -Eeuo pipefail
source_dir="$GITHUB_WORKSPACE/private-source/$IOS_PROJECT_DIRECTORY"
derived_data="$RUNNER_TEMP/ios-derived"
source_revision="$(git -C "$GITHUB_WORKSPACE/private-source" rev-parse HEAD)"
sentry_release="$(printf '%s' "$IOS_SCHEME" | tr '[:upper:]' '[:lower:]')-ios@$source_revision"

set +e
xcodebuild -quiet \
  -project "$source_dir/$IOS_SCHEME.xcodeproj" \
  -scheme "$IOS_SCHEME" \
  -configuration Release \
  -sdk iphoneos \
  -destination 'generic/platform=iOS' \
  -derivedDataPath "$derived_data" \
  -clonedSourcePackagesDirPath "$RUNNER_TEMP/ios-source-packages" \
  ARCHS=arm64 \
  ONLY_ACTIVE_ARCH=NO \
  SENTRY_DSN="${SENTRY_IOS_DSN:-}" \
  SENTRY_RELEASE="$sentry_release" \
  SENTRY_ENVIRONMENT="$SENTRY_ENVIRONMENT" \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGNING_REQUIRED=NO \
  build >"$RUNNER_TEMP/xcodebuild.log" 2>&1
build_status=$?
set -e

if [ "$build_status" -ne 0 ]; then
  echo "::error title=iOS build failed::The unsigned iPhone build failed (exit $build_status); private Xcode diagnostics were suppressed."
  exit "$build_status"
fi

app_path="$derived_data/Build/Products/Release-iphoneos/$IOS_SCHEME.app"
if [[ ! -d "$app_path" ]]; then
  echo "::error title=IPA packaging failed::Xcode completed but the expected app bundle was not found."
  exit 1
fi

package_path="$RUNNER_TEMP/ios-package"
mkdir -p "$package_path/Payload"
ditto "$app_path" "$package_path/Payload/$IOS_SCHEME.app"
(cd "$package_path" && /usr/bin/zip -qry "$RUNNER_TEMP/app-unsigned.ipa" Payload)
echo "The unsigned arm64 iPhone IPA was built on the ephemeral runner."
