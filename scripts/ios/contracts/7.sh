#!/usr/bin/env bash
set -euo pipefail
swiftc \
  ios/KnightRoute/KnightRoute/Models/RouteLineHitTest.swift \
  tests/swift/RouteLineHitCheck.swift \
  -o "$RUNNER_TEMP/route-line-hit-check"
"$RUNNER_TEMP/route-line-hit-check"
