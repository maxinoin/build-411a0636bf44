# Private-source GitHub App setup

The private Tailspin diagnostic workflow can use short-lived GitHub App installation tokens instead of manually expiring PATs. Existing PAT secrets remain a fallback until the App is configured and verified.

## Create and install the App

1. In the `maxinoin` GitHub account, create a GitHub App with no webhook URL and no event subscriptions.
2. Grant the App **Contents: read and write** repository permission. The workflow requests a read-only token for checkout and a separate write-scoped token for uploading the report.
3. Install the App on **only** the private `maxinoin/KnightRoute` repository.
4. Generate a private key for the App. Keep the downloaded PEM private; do not commit or paste it into chat.

## Configure the public build broker

In `maxinoin/build-411a0636bf44`, open **Settings → Secrets and variables → Actions** and add:

- Repository variable `PRIVATE_SOURCE_GITHUB_APP_CLIENT_ID`: the App's Client ID.
- Repository secret `PRIVATE_SOURCE_GITHUB_APP_PRIVATE_KEY`: the full PEM private-key text.

The workflow pins `actions/create-github-app-token` to its v3 commit and scopes each generated token to `maxinoin/KnightRoute`. Installation tokens expire after one hour and are revoked when the job finishes.

## Manual IPA builds from the shared queue

Completed iOS changes should be integrated into `maxinoin/KnightRoute` branch `codex/ipa-queue`. Pushing changes there only stages them; it does not start a build. When the user asks for an IPA, manually run **Actions → Build iOS** in this broker. Leaving `private_source_sha` blank builds the latest queue head; setting it builds that exact full commit SHA. The workflow uses the same short-lived App tokens above for private checkout and private prerelease upload, so the App can replace expiring PATs. The IPA is uploaded to a private prerelease and is not downloaded to the user's computer automatically.

## Verify and retire the PAT fallback

Run **Actions → Analyze private iOS Tailspin → Run workflow** on `main`. A successful run using the App confirms both read access and private prerelease upload. Then remove the old `PRIVATE_SOURCE_READ_TOKEN` and `PRIVATE_IPA_UPLOAD_TOKEN` repository secrets. Until that verification succeeds, keep them as fallback credentials.

Protect the broker's `main` branch and limit who can change workflows, because workflows on this public repository can access its configured secrets.
