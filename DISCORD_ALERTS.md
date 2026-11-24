# Discord dependency alerts

The dependency broker can mention one Discord user on each alert and on the manual webhook test. It only allows the configured user ID to be mentioned; it does not enable `@everyone`, `@here`, or role mentions.

To enable the ping, add a repository Actions secret in `maxinoin/build-411a0636bf44`:

- Name: `DISCORD_USER_ID`
- Value: your numeric Discord user ID

In Discord, enable **User Settings → Advanced → Developer Mode**, then right-click your profile and choose **Copy User ID**. Keep the existing `DISCORD_WEBHOOK_URL` secret as-is. Do not put either value in the repository or a workflow file.

After adding the secret, run **Actions → Dependency checks → Run workflow** with `test_webhook` checked. That sends one test message mentioning the configured user and skips dependency checks. If `DISCORD_USER_ID` is unset, messages continue to post without a ping. Discord notification preferences or channel mute settings can still suppress a push notification.
