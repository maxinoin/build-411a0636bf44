#!/usr/bin/env bash
set -euo pipefail
swiftc \
  ios/KnightRoute/KnightRoute/Models/SheetGesturePolicy.swift \
  ios/KnightRoute/KnightRoute/Models/RoutePagination.swift \
  ios/KnightRoute/KnightRoute/Models/RoutePickerLayout.swift \
  tests/swift/SheetGesturePolicyCheck.swift \
  -o "$RUNNER_TEMP/sheet-gesture-policy-check"
"$RUNNER_TEMP/sheet-gesture-policy-check"
