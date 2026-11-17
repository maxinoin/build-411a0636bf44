#!/usr/bin/env bash
set -euo pipefail
swiftc \
  ios/KnightRoute/KnightRoute/Models/RouteCameraFocus.swift \
  tests/swift/RouteCameraFocusCheck.swift \
  -o "$RUNNER_TEMP/route-camera-focus-check"
"$RUNNER_TEMP/route-camera-focus-check" \
  ios/KnightRoute/KnightRoute/App/TransitStore.swift \
  ios/KnightRoute/KnightRoute/Views/ContentView.swift \
  ios/KnightRoute/KnightRoute/Map/TransitMapView.swift
