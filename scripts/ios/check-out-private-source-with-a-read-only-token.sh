#!/usr/bin/env bash
set -Eeuo pipefail
if [[ ! "$PRIVATE_SOURCE_REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || [[ -z "$PRIVATE_SOURCE_READ_TOKEN" ]]; then
  echo "::error title=Checkout configuration invalid::Configure the private source repository and read token."
  exit 1
fi
askpass="$RUNNER_TEMP/private-source-askpass"
trap 'rm -f "$askpass"' EXIT
umask 077
cat >"$askpass" <<'ASKPASS'
#!/bin/sh
case "$1" in
  *Username*) printf '%s\n' 'x-access-token' ;;
  *Password*) printf '%s\n' "$PRIVATE_SOURCE_READ_TOKEN" ;;
  *) exit 1 ;;
esac
ASKPASS
chmod 700 "$askpass"
export GIT_ASKPASS="$askpass"
source="$GITHUB_WORKSPACE/private-source"
if [[ "$REQUESTED_REVISION" =~ ^[0-9a-f]{40}$ ]]; then
  revision_ref="$REQUESTED_REVISION"
else
  echo "::error title=Invalid private revision::The resolved private revision is not a full lowercase commit SHA."
  exit 1
fi
if ! (
  git init --quiet "$source"
  git -C "$source" -c credential.helper= fetch --quiet --depth 1 \
    "https://github.com/$PRIVATE_SOURCE_REPOSITORY.git" "$revision_ref"
  git -C "$source" checkout --quiet --detach FETCH_HEAD
) >"$RUNNER_TEMP/private-checkout.log" 2>&1; then
  echo "::error title=Private checkout failed::Source checkout failed; private diagnostics were suppressed."
  exit 1
fi
revision="$(git -C "$source" rev-parse HEAD)"
if [[ -n "$REQUESTED_REVISION" && "$revision" != "$REQUESTED_REVISION" ]]; then
  echo "::error title=Private revision mismatch::The checked out commit did not match the requested commit."
  exit 1
fi
echo "::add-mask::$revision"
echo "Private source checkout completed."
