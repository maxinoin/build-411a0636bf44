#!/usr/bin/env bash
set -euo pipefail
if [[ ! "$PRIVATE_SOURCE_REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo "::error title=Private source configuration invalid::The private source repository is not configured."
  exit 1
fi
if [[ -n "$APP_CLIENT_ID" || "$APP_PRIVATE_KEY_CONFIGURED" == "true" ]]; then
  if [[ -z "$APP_CLIENT_ID" || "$APP_PRIVATE_KEY_CONFIGURED" != "true" ]]; then
    echo "::error title=GitHub App configuration incomplete::Set both PRIVATE_SOURCE_GITHUB_APP_CLIENT_ID and PRIVATE_SOURCE_GITHUB_APP_PRIVATE_KEY."
    exit 1
  fi
  if [[ "$PRIVATE_SOURCE_REPOSITORY" != "maxinoin/KnightRoute" ]]; then
    echo "::error title=GitHub App repository mismatch::The App token is scoped to maxinoin/KnightRoute."
    exit 1
  fi
  echo "auth_mode=app" >> "$GITHUB_OUTPUT"
elif [[ "$SOURCE_TOKEN_CONFIGURED" == "true" && "$UPLOAD_TOKEN_CONFIGURED" == "true" ]]; then
  echo "auth_mode=pat" >> "$GITHUB_OUTPUT"
  echo "::notice title=Legacy token fallback::Using PAT secrets. Configure the GitHub App credentials to avoid expiring tokens."
else
  echo "::error title=Private source authentication missing::Configure the GitHub App credentials or both fallback PAT secrets."
  exit 1
fi
