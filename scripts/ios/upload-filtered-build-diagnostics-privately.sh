#!/usr/bin/env bash
set -Eeuo pipefail
source_log="$RUNNER_TEMP/xcodebuild.log"
diagnostics="$RUNNER_TEMP/ios-build-diagnostics.txt"
python3 - "$source_log" "$diagnostics" <<'PY'
import pathlib
import re
import json
import os
import subprocess
import sys
source = pathlib.Path(sys.argv[1])
output = pathlib.Path(sys.argv[2])
lines = source.read_text(errors="replace").splitlines() if source.exists() else []
pattern = re.compile(r"(?:\.swift:\d+:\d+:\s+error:|(?:^|\s)xcodebuild:\s+error:|^\s*error:|\*\* BUILD FAILED \*\*)")
selected = [re.sub(r"^.*?/private-source/", "private-source/", line) for line in lines if pattern.search(line)]
test_log = pathlib.Path(str(source).replace("xcodebuild.log", "xcode-test.log"))
test_lines = test_log.read_text(errors="replace").splitlines() if test_log.exists() else []
# The simulator runner records both build-for-testing and test-without-building
# output in xcode-test.log. Include actionable compiler/command failures only.
command_error_pattern = re.compile(
    r"(?:\.swift:\d+:\d+:\s+(?:fatal )?error:|(?:^|\s)xcodebuild:\s+error:|^\s*error:|"
    r"\*\* (?:BUILD|TEST) FAILED \*\*)",
    re.IGNORECASE,
)
simulator_diagnostics = [
    "Simulator build/test: " + re.sub(r"^.*?/private-source/", "private-source/", line)[:800]
    for line in test_lines if command_error_pattern.search(line)
]
test_pattern = re.compile(
    r"(?:Test Case .*\bfailed\b|Test Suite .*\bfailed\b|"
    r"Failing tests:|Executed \d+ tests?|Testing failed|"
    r"XCTAssert\w* failed|Assertion Failure|error:.*(?:XCTAssert|test case))",
    re.IGNORECASE,
)
test_details = [
    re.sub(r"^.*?/private-source/", "private-source/", line)[:800]
    for line in test_lines if test_pattern.search(line)
]
report = selected[:]
if simulator_diagnostics:
    report.append("Simulator build/test diagnostics:")
    report.extend(simulator_diagnostics[:80])
if not report:
    report.append("No compiler diagnostic lines matched; full build logs stayed on the ephemeral runner.")
report.append("")
report.append("UI test failure summary:")
report.extend(test_details[:80])
result_bundle = pathlib.Path(os.environ["XCRESULT_BUNDLE"])
if result_bundle.exists():
    try:
        result = subprocess.run(
            ["xcrun", "xcresulttool", "get", "test-results", "summary",
             "--path", str(result_bundle), "--format", "json"],
            check=True, capture_output=True, text=True, timeout=20,
        )
        summary = json.loads(result.stdout)
        summary_fields = {
            key: summary[key] for key in
            ("title", "result", "totalTestCount", "passedTests", "failedTests", "skippedTests")
            if key in summary
        }
        if summary_fields:
            report.append("XCResult totals:")
            report.append(json.dumps(summary_fields, sort_keys=True))

        failures = []
        def collect_failures(value):
            if isinstance(value, dict):
                failure_text = value.get("failureText") or value.get("message")
                identifier = value.get("testIdentifier") or value.get("nodeIdentifier") or value.get("name")
                if failure_text and identifier:
                    failures.append((str(identifier), str(failure_text)))
                for child in value.values():
                    collect_failures(child)
            elif isinstance(value, list):
                for child in value:
                    collect_failures(child)
        collect_failures(summary)
        if failures:
            report.append("XCResult failure details:")
            for identifier, message in failures[:40]:
                report.append(f"{identifier}: {message[:800]}")
    except Exception:
        report.append("XCResult summary could not be decoded; the bundle remains on the ephemeral runner.")
if not test_details and len(report) == 3:
    report.append("No filtered XCTest failure lines matched; full test logs stayed on the ephemeral runner.")
output.write_text("\n".join(report) + "\n")
PY

if ! command -v gh >/dev/null 2>&1; then
  if ! brew install --quiet gh >/dev/null 2>&1; then
    echo "::error title=Private diagnostics unavailable::Could not install GitHub CLI."
    exit 1
  fi
fi
if ! destination_private="$(gh api "repos/$PRIVATE_SOURCE_REPOSITORY" --jq '.private' 2>/dev/null)" || [[ "$destination_private" != "true" ]]; then
  echo "::error title=Private diagnostics blocked::The destination could not be verified as private."
  exit 1
fi
release_tag="ios-build-diagnostics-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
files=("$diagnostics")
for contract_log in "$RUNNER_TEMP"/contract-*.log; do
  [[ -f "$contract_log" ]] && files+=("$contract_log")
done
if ! gh release create "$release_tag" "${files[@]}" \
  --repo "$PRIVATE_SOURCE_REPOSITORY" \
  --target "$(git -C "$GITHUB_WORKSPACE/private-source" rev-parse HEAD)" \
  --latest=false \
  --title "Private iOS build diagnostics ${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}" \
  --notes "Filtered compiler and XCTest failure details from the private iOS build. Full source and test logs were not uploaded." \
  --prerelease >"$RUNNER_TEMP/private-diagnostics-upload.log" 2>&1; then
  echo "::error title=Private diagnostics upload failed::Could not upload filtered diagnostics."
  exit 1
fi
echo "Filtered build diagnostics uploaded to a private prerelease."
