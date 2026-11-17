#!/usr/bin/env bash
set -euo pipefail
swiftc \
  ios/KnightRoute/KnightRoute/Models/TransitModels.swift \
  ios/KnightRoute/KnightRoute/Models/PolylineDecoder.swift \
  ios/KnightRoute/KnightRoute/Models/VehicleSnapshotBuffer.swift \
  tests/swift/VehicleSnapshotCheck.swift \
  -o "$RUNNER_TEMP/vehicle-snapshot-check"
"$RUNNER_TEMP/vehicle-snapshot-check" tests/fixtures
