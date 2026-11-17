#!/usr/bin/env bash
set -euo pipefail
swiftc ios/KnightRoute/KnightRoute/Models/VehicleMotionPolicy.swift \
  tests/swift/VehicleMotionCheck.swift -o "$RUNNER_TEMP/vehicle-motion-check"
"$RUNNER_TEMP/vehicle-motion-check"
