#!/usr/bin/env bash
set -Eeuo pipefail
source_dir="$GITHUB_WORKSPACE/private-source/$IOS_PROJECT_DIRECTORY"
simulator_id=$(xcrun simctl list devices available -j | python3 -c 'import json,sys; devices=json.load(sys.stdin)["devices"]; print(next(device["udid"] for runtime,rows in devices.items() if "iOS" in runtime for device in rows if device["name"].startswith("iPhone")))') || {
  echo "::error title=Simulator unavailable::No available iPhone Simulator was found."
  exit 1
}

xcodebuild_test_args=(test)
test_workers=2
test_parallel=YES
case "${TEST_SHARD:-focused}" in
  focused)
    case "${TEST_SUITE:-full}" in
      full) ;;
      sheets) xcodebuild_test_args+=(-only-testing:KnightRouteSheetUITests/SheetStateVisualTests) ;;
      picker) xcodebuild_test_args+=(-only-testing:KnightRouteSheetUITests/RoutePickerTransitionTests) ;;
      startup) xcodebuild_test_args+=(-only-testing:KnightRouteSheetUITests/StartupTests) ;;
      map) xcodebuild_test_args+=(-only-testing:KnightRouteSheetUITests/MapInteractionTests) ;;
      gestures)
        xcodebuild_test_args+=(-only-testing:KnightRouteSheetUITests/SheetGestureTests
          -only-testing:KnightRouteSheetUITests/SettingsDismissalTests) ;;
      ownership-check)
        xcodebuild_test_args+=(
          -only-testing:KnightRouteSheetUITests/SheetGestureOwnershipTests/testMapBackdropTapDismissesRoutePicker
          -only-testing:KnightRouteSheetUITests/SheetGestureOwnershipTests/testRouteArrivalRowLimitIsConfigurable
          -only-testing:KnightRouteSheetUITests/SheetGestureOwnershipTests/testSelectingStopFromFullRouteSheetSizesToMeasuredContent
        )
        test_workers=1
        test_parallel=NO ;;
      ownership)
        xcodebuild_test_args+=(-only-testing:KnightRouteSheetUITests/SheetGestureOwnershipTests)
        # This focused suite exercises MapKit gestures. Running cloned app
        # launches in parallel has caused simulator launch-progress timeouts.
        test_workers=1
        test_parallel=NO ;;
      *) echo "::error::Unknown focused test suite"; exit 1 ;;
    esac ;;
  map) xcodebuild_test_args+=(-only-testing:KnightRouteSheetUITests/MapInteractionTests); test_workers=1; test_parallel=NO ;;
  visuals) xcodebuild_test_args+=(-only-testing:KnightRouteSheetUITests/SheetStateVisualTests); test_workers=1; test_parallel=NO ;;
  ownership) xcodebuild_test_args+=(-only-testing:KnightRouteSheetUITests/SheetGestureOwnershipTests); test_workers=1; test_parallel=NO ;;
  gestures)
    xcodebuild_test_args+=(-only-testing:KnightRouteSheetUITests/SheetGestureTests
      -only-testing:KnightRouteSheetUITests/SettingsDismissalTests); test_workers=1; test_parallel=NO ;;
  startup-picker)
    xcodebuild_test_args+=(-only-testing:KnightRouteSheetUITests/StartupTests
      -only-testing:KnightRouteSheetUITests/RoutePickerTransitionTests); test_workers=1; test_parallel=NO ;;
  *) echo "::error::Unknown simulator test shard"; exit 1 ;;
esac
test_allowance=180
test_maximum=240
if [[ "${TEST_SUITE:-full}" == full ]]; then
  test_allowance=600
  test_maximum=600
fi
set +e
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
# Full-suite shards run one worker each because the workflow spreads them
# across five independent Mac runners. The focused ownership suite also uses
# one local worker because its MapKit gestures are unstable across clones.
xcodebuild "${xcodebuild_test_args[@]}" \
  -project "$source_dir/$IOS_SCHEME.xcodeproj" \
  -scheme "$IOS_SCHEME" \
  -configuration Debug \
  -destination "platform=iOS Simulator,id=$simulator_id" \
  -derivedDataPath "$RUNNER_TEMP/ios-derived" \
  -clonedSourcePackagesDirPath "$RUNNER_TEMP/ios-source-packages" \
  -resultBundlePath "$RUNNER_TEMP/ios-ui-tests.xcresult" \
  -parallel-testing-enabled "$test_parallel" \
  -parallel-testing-worker-count "$test_workers" \
  -test-timeouts-enabled YES \
  -default-test-execution-time-allowance "$test_allowance" \
  -maximum-test-execution-time-allowance "$test_maximum" \
  CODE_SIGNING_ALLOWED=NO \
  >>"$RUNNER_TEMP/xcode-test.log" 2>&1
test_status=$?
if [[ -d "$RUNNER_TEMP/ios-ui-tests.xcresult" ]]; then
  echo "suite_ran=true" >> "$GITHUB_OUTPUT"
fi
xcrun simctl spawn "$simulator_id" log show --last 5m --style compact \
  --predicate 'subsystem == "com.knighteta.app" AND category == "Startup"' >>"$RUNNER_TEMP/xcode-test.log" 2>&1 || true
set -e

if [ "$test_status" -ne 0 ]; then
  echo "::error title=Simulator tests failed::The iOS Simulator tests failed (exit $test_status); private test diagnostics were suppressed."
  exit "$test_status"
fi

echo "The optional iOS Simulator UI test suite passed."
