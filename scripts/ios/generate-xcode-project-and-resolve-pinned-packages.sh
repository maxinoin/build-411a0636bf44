#!/usr/bin/env bash
set -Eeuo pipefail
if [[ ! "$IOS_PROJECT_DIRECTORY" =~ ^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$ ]] ||
   [[ "/$IOS_PROJECT_DIRECTORY/" == *"/../"* ]] ||
   [[ ! "$IOS_SCHEME" =~ ^[A-Za-z0-9_.-]+$ ]]; then
  echo "::error title=Build configuration invalid::Configure the private project directory and scheme secrets."
  exit 1
fi
source_dir="$GITHUB_WORKSPACE/private-source/$IOS_PROJECT_DIRECTORY"

export PATH="$RUNNER_TEMP/ios-tools:$PATH"
if ! command -v xcodegen >/dev/null 2>&1; then
  if ! brew install --quiet xcodegen >/dev/null 2>&1; then
    echo "::error title=Build setup failed::Could not install XcodeGen; installer output was suppressed."
    exit 1
  fi
fi

if ! (cd "$source_dir" && xcodegen generate --spec project.yml) \
  >"$RUNNER_TEMP/xcodegen.log" 2>&1; then
  echo "::error title=Project generation failed::XcodeGen failed; private project diagnostics were suppressed."
  exit 1
fi

mkdir -p "$RUNNER_TEMP/ios-derived" "$RUNNER_TEMP/ios-source-packages"
set +e
xcodebuild -resolvePackageDependencies \
  -project "$source_dir/$IOS_SCHEME.xcodeproj" \
  -scheme "$IOS_SCHEME" \
  -clonedSourcePackagesDirPath "$RUNNER_TEMP/ios-source-packages" \
  >"$RUNNER_TEMP/package-resolution.log" 2>&1
resolve_status=$?
set -e

if [ "$resolve_status" -ne 0 ]; then
  echo "::error title=Dependency resolution failed::Swift package resolution failed; private dependency diagnostics were suppressed."
  exit "$resolve_status"
fi

echo "The app's pinned Swift packages resolved successfully."
