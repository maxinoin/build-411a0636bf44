#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd "$(dirname "$0")" && pwd)
cd "$GITHUB_WORKSPACE/private-source"
pids=()
pending=0
status=0
# Bound parallel compiler processes to two on the Mac runner.
for script in "$script_dir"/contracts/*.sh; do
  bash "$script" >"$RUNNER_TEMP/contract-$(basename "$script").log" 2>&1 &
  pids+=("$!")
  pending=$((pending + 1))
  if [[ "$pending" == 2 ]]; then
    for pid in "${pids[@]}"; do wait "$pid" || status=1; done
    pids=()
    pending=0
  fi
done
if [[ "$pending" -gt 0 ]]; then
  for pid in "${pids[@]}"; do wait "$pid" || status=1; done
fi
if [[ "$status" != 0 ]]; then echo "::error::Swift contracts failed; private logs will be uploaded."; fi
exit "$status"
