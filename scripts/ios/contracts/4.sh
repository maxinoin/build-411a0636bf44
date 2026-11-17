#!/usr/bin/env bash
set -euo pipefail
swiftc \
  ios/KnightRoute/KnightRoute/Models/RoutePickerSearch.swift \
  tests/swift/RoutePickerCheck.swift \
  -o "$RUNNER_TEMP/route-picker-check"
"$RUNNER_TEMP/route-picker-check" ios/KnightRoute/KnightRoute/Views/RoutePickerView.swift
