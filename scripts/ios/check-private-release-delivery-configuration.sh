#!/usr/bin/env bash
if [[ -z "$APP_CLIENT_ID" || "$APP_PRIVATE_KEY_CONFIGURED" != "true" ]] && [[ "$TOKEN_CONFIGURED" != "true" ]]; then
  echo "::error title=Private IPA delivery is not configured::Configure the GitHub App credentials or PRIVATE_IPA_UPLOAD_TOKEN."
  exit 1
fi
