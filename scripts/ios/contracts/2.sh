#!/usr/bin/env bash
set -euo pipefail
swiftc \
  ios/KnightRoute/KnightRoute/Models/BusMarkerContrast.swift \
  tests/swift/BusMarkerContrastCheck.swift \
  -o "$RUNNER_TEMP/bus-marker-contrast-check"
"$RUNNER_TEMP/bus-marker-contrast-check"
