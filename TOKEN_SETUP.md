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

## Automatic IPA queue

The `Build iOS` workflow checks the private `codex/ipa-queue` branch every 15 minutes. It builds the newest queue revision only once, runs the iOS Simulator suite, and uploads the unsigned IPA to a private prerelease in `maxinoin/KnightRoute`. It uses the same short-lived App tokens above for private checkout, release upload, and a private processed-revision tag; it does not require a cross-repository dispatch token. Multiple commits pushed close together are coalesced into the latest queue head. A failed revision is not retried automatically to avoid repeatedly spending Mac runner minutes; use workflow dispatch to retry that SHA. The scheduled event can be delayed by GitHub Actions load.

The queue automation does not download the IPA to the user's computer. The private prerelease remains available for retrieval after the build.

## Verify and retire the PAT fallback

Run **Actions → Analyze private iOS Tailspin → Run workflow** on `main`. A successful run using the App confirms both read access and private prerelease upload. Then remove the old `PRIVATE_SOURCE_READ_TOKEN` and `PRIVATE_IPA_UPLOAD_TOKEN` repository secrets. Until that verification succeeds, keep them as fallback credentials.

Protect the broker's `main` branch and limit who can change workflows, because workflows on this public repository can access its configured secrets.
