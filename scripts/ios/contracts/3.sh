#!/usr/bin/env bash
set -euo pipefail
swiftc \
  ios/KnightRoute/KnightRoute/Models/SheetMetrics.swift \
  ios/KnightRoute/KnightRoute/Models/RoutePickerLayout.swift \
  tests/swift/SheetConfigurationCheck.swift \
  -o "$RUNNER_TEMP/route-sheet-motion-check"
"$RUNNER_TEMP/route-sheet-motion-check" \
  ios/KnightRoute/KnightRoute/Views/FloatingRouteSheet.swift \
  ios/KnightRoute/KnightRoute/Views/RoutePickerView.swift
