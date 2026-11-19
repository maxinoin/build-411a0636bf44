#!/usr/bin/env bash
set -Eeuo pipefail
source_dir="$GITHUB_WORKSPACE/private-source/$IOS_PROJECT_DIRECTORY"
simulator_id=$(xcrun simctl list devices available -j | python3 -c 'import json,sys; devices=json.load(sys.stdin)["devices"]; print(next(device["udid"] for runtime,rows in devices.items() if "iOS" in runtime for device in rows if device["name"].startswith("iPhone")))') || {
  echo "::error title=Simulator unavailable::No available iPhone Simulator was found."
  exit 1
}

if [[ "$VISUAL_AUDIT" == "true" && "$VISUAL_ROUTE_ONLY" == "true" ]]; then
  xcodebuild build \
    -project "$source_dir/$IOS_SCHEME.xcodeproj" -scheme "$IOS_SCHEME" \
    -configuration Debug -destination "platform=iOS Simulator,id=$simulator_id" \
    -derivedDataPath "$RUNNER_TEMP/ios-derived" \
    -clonedSourcePackagesDirPath "$RUNNER_TEMP/ios-source-packages" \
    CODE_SIGNING_ALLOWED=NO >"$RUNNER_TEMP/xcode-test.log" 2>&1
  xcrun simctl boot "$simulator_id" >/dev/null 2>&1 || true
  xcrun simctl bootstatus "$simulator_id" -b >>"$RUNNER_TEMP/xcode-test.log" 2>&1
  app_path="$RUNNER_TEMP/ios-derived/Build/Products/Debug-iphonesimulator/$IOS_SCHEME.app"
  bundle_id=$(/usr/libexec/PlistBuddy -c 'Print CFBundleIdentifier' "$app_path/Info.plist")
  xcrun simctl install "$simulator_id" "$app_path" >>"$RUNNER_TEMP/xcode-test.log" 2>&1
  xcrun simctl ui "$simulator_id" appearance dark
  xcrun simctl launch "$simulator_id" "$bundle_id" \
    --design-preview --map-interaction-test -knightGoAppearance dark \
    -knightGoArrivalDisplayMode knightGo -knightGoOnboardingCompleted YES \
    -knightGoLastSelectedRouteID 1 >>"$RUNNER_TEMP/xcode-test.log" 2>&1
  mkdir -p "$RUNNER_TEMP/live-route-captures"
  for sample in $(seq 1 6); do
    sleep 5
    xcrun simctl io "$simulator_id" screenshot \
      "$RUNNER_TEMP/live-route-captures/route-preview-$sample.png" >>"$RUNNER_TEMP/xcode-test.log" 2>&1
  done
  echo "test_run_mode=build-only" >> "$GITHUB_OUTPUT"
  echo "Route preview captured from the launched app."
  exit 0
fi
set +e
xcodebuild_test_args=(test)
case "${TEST_SUITE:-full}" in
  full) ;;
  sheets) xcodebuild_test_args+=(-only-testing:KnightRouteSheetUITests/SheetStateVisualTests) ;;
  picker) xcodebuild_test_args+=(-only-testing:KnightRouteSheetUITests/RoutePickerTransitionTests) ;;
  startup) xcodebuild_test_args+=(-only-testing:KnightRouteSheetUITests/StartupTests) ;;
  *) echo "::error::Unknown test suite"; exit 1 ;;
esac
test_allowance=180
test_maximum=240
if [[ "$VISUAL_AUDIT" == "true" ]]; then
  # A full visual audit runs the complete regression suite; the sheet tests
  # already capture the screenshots that will be reviewed for this revision.
  if [[ "${TEST_SUITE:-full}" != full ]]; then
    xcodebuild_test_args+=(-only-testing:KnightRouteSheetUITests/SheetStateVisualTests)
  fi
  if [[ "$VISUAL_OTHER_SHEETS_ONLY" == "true" ]]; then
    xcodebuild_test_args=(test -only-testing:KnightRouteSheetUITests/SheetStateVisualTests/testOtherSheetsInDarkMode -only-testing:KnightRouteSheetUITests/SheetStateVisualTests/testOtherSheetsInLightMode)
  fi
  if [[ "$VISUAL_BUS_ONLY" == "true" ]]; then
    xcodebuild_test_args=(test -only-testing:KnightRouteSheetUITests/SheetStateVisualTests/testBusStatesInDarkMode -only-testing:KnightRouteSheetUITests/SheetStateVisualTests/testBusStatesInLightMode)
  fi
  if [[ "$VISUAL_ROUTE_ONLY" == "true" ]]; then
    xcodebuild_test_args=(test -only-testing:KnightRouteSheetUITests/SheetStateVisualTests/testRoutePreview)
  fi
  if [[ "${TEST_SUITE:-full}" == startup ]]; then
    xcodebuild_test_args=(test -only-testing:KnightRouteSheetUITests/StartupTests)
  fi
  test_allowance=600
  test_maximum=600
fi
echo "Compiling simulator test products."
xcodebuild build-for-testing \
  -project "$source_dir/$IOS_SCHEME.xcodeproj" -scheme "$IOS_SCHEME" \
  -configuration Debug -destination "platform=iOS Simulator,id=$simulator_id" \
  -derivedDataPath "$RUNNER_TEMP/ios-derived" \
  -clonedSourcePackagesDirPath "$RUNNER_TEMP/ios-source-packages" \
  CODE_SIGNING_ALLOWED=NO >"$RUNNER_TEMP/xcode-test.log" 2>&1
build_status=$?
if [[ "$build_status" -ne 0 ]]; then exit "$build_status"; fi
xcodebuild_test_args[0]=test-without-building
echo "Running tests using compiled simulator products."
xcodebuild "${xcodebuild_test_args[@]}" \
  -project "$source_dir/$IOS_SCHEME.xcodeproj" \
  -scheme "$IOS_SCHEME" \
  -configuration Debug \
  -destination "platform=iOS Simulator,id=$simulator_id" \
  -derivedDataPath "$RUNNER_TEMP/ios-derived" \
  -clonedSourcePackagesDirPath "$RUNNER_TEMP/ios-source-packages" \
  -resultBundlePath "$RUNNER_TEMP/ios-ui-tests.xcresult" \
  -parallel-testing-enabled NO \
  -test-timeouts-enabled YES \
  -default-test-execution-time-allowance "$test_allowance" \
  -maximum-test-execution-time-allowance "$test_maximum" \
  CODE_SIGNING_ALLOWED=NO \
  >>"$RUNNER_TEMP/xcode-test.log" 2>&1
test_status=$?
echo "test_run_mode=xctest" >> "$GITHUB_OUTPUT"
xcrun simctl spawn "$simulator_id" log show --last 5m --style compact \
  --predicate 'subsystem == "com.knighteta.app" AND category == "Startup"' >>"$RUNNER_TEMP/xcode-test.log" 2>&1 || true
set -e

if [ "$test_status" -ne 0 ]; then
  echo "::error title=Simulator tests failed::The iOS Simulator tests failed (exit $test_status); private test diagnostics were suppressed."
  exit "$test_status"
fi

echo "The optional iOS Simulator UI test suite passed."
