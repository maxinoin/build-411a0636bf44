#!/usr/bin/env bash
set -Eeuo pipefail
source_dir="$GITHUB_WORKSPACE/private-source/$IOS_PROJECT_DIRECTORY"
derived_data="$RUNNER_TEMP/ios-derived"
source_revision="$(git -C "$GITHUB_WORKSPACE/private-source" rev-parse HEAD)"
app_variant="${APP_VARIANT:-dev}"
case "$app_variant" in
  dev)
    build_flavor="dev"
    bundle_identifier="com.knighteta.app.dev"
    display_name="KnightRoute Dev"
    default_scenario="multiple"
    developer_preview="YES"
    api_base_url="http://localhost:8000"
    ;;
  production)
    build_flavor="production"
    bundle_identifier="com.knighteta.app"
    display_name="KnightRoute"
    default_scenario="live"
    developer_preview="NO"
    api_base_url="https://129-158-208-229.sslip.io"
    ;;
  *)
    echo "::error title=Build configuration invalid::Choose app_variant dev or production."
    exit 1
    ;;
esac
sentry_release="$(printf '%s' "$IOS_SCHEME-$app_variant" | tr '[:upper:]' '[:lower:]')-ios@$source_revision"
build_number_base=2026112401
if [[ ! "${GITHUB_RUN_NUMBER:-}" =~ ^[0-9]+$ ]]; then
  echo "::error title=iOS build version unavailable::The workflow run number is missing."
  exit 1
fi
build_number=$((build_number_base + GITHUB_RUN_NUMBER))
echo "Building ${app_variant} IPA with build number ${build_number}."

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
  KNIGHTROUTE_BUILD_FLAVOR="$build_flavor" \
  KNIGHTROUTE_DEVELOPER_PREVIEW="$developer_preview" \
  KNIGHTROUTE_DEFAULT_BUS_SCENARIO="$default_scenario" \
  KNIGHTROUTE_DISPLAY_NAME="$display_name" \
  KNIGHTROUTE_API_BASE_URL="$api_base_url" \
  PRODUCT_BUNDLE_IDENTIFIER="$bundle_identifier" \
  CURRENT_PROJECT_VERSION="$build_number" \
  KNIGHTROUTE_SHEET_STYLE="${KNIGHTROUTE_SHEET_STYLE:-colored-divider-only}" \
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
