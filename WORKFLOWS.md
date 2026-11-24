# iOS operations

Builds are dispatched manually for Dev and automatically for published Production releases from the private KnightRoute repository. The public broker reads the exact private source revision supplied by the caller, or the shared `codex/ipa-queue` revision for a direct manual dispatch.

| Operation | Inputs | Validation |
| --- | --- | --- |
| Swift contracts only | deliver_private_ipa=false, run_ui_tests=false | Independent Swift checks in parallel |
| Focused tests | deliver_private_ipa=false, run_ui_tests=true, test_suite=picker, sheets, startup, map, gestures or ownership | Swift contracts plus selected simulator tests |
| Full tests | deliver_private_ipa=false, run_ui_tests=true, test_suite=full | Five parallel macOS shards; all five must pass |
| Dev IPA, on demand | app_variant=dev, deliver_private_ipa=true | Local sample data starts enabled; simulation controls are available |
| Production IPA, on release | app_variant=production, deliver_private_ipa=true | Live service is used; simulation controls are disabled |
| IPA, tested | deliver_private_ipa=true, run_ui_tests=true | Five parallel macOS shards; packaging starts only after the full suite passes |
| IPA, manual test build | deliver_private_ipa=true, run_ui_tests=false | UI tests are skipped; release is labeled with app variant, sheet style and test status |

Scripts live in `scripts/ios`. Each run checks out the exact public workflow revision. The full suite splits into map, sheet visuals, gesture ownership, gestures/settings, and startup/route picker shards. Each shard runs on its own Mac runner with one simulator; focused suites use one Mac runner with two simulator workers. Device Release products require a separate compilation.

Dependency cache assets live exclusively in private KnightRoute prereleases tagged `ios-dependencies-v1-*`. Keys include the project specification, Xcode version, architecture and cache schema. Only downloaded Swift packages are cached; app source, credentials, data and DerivedData are excluded. Delete these private cache releases to clear the cache. Missing caches resolve dependencies normally. Saving a cache is best effort; tests and builds still decide success.

Test-only and IPA operations use separate concurrency groups. Backend checks stay on the developer PC. The private legacy build entry points users to this broker.

## IPA delivery

One dispatch builds an unsigned IPA for a private prerelease. Choose `app_variant` to build Dev or Production and `sheet_style` to build the accent-rail/gray-divider or colored-divider-only variant. Dev starts with local sample data and exposes simulation controls; switching it to live uses localhost only. Production uses the configured live service and does not expose simulation controls. Both variants use the same app target, map, ETA, and UI source. The `private_source_sha` input selects the exact private revision; with the input empty, a direct manual Dev dispatch resolves the current queue commit. Production also requires `production_release_tag`; the broker verifies the source release is published, non-prerelease, and points to that exact commit.

The private repository's release workflow dispatches Production builds to this broker. It requires a repository Actions secret named `KNIGHTROUTE_IPA_BROKER_TOKEN` with `actions:write` access to this broker repository. That credential is used only by GitHub Actions to start the broker workflow; it is not passed to Xcode or included in either IPA. The private release workflow uses the same dispatch for an on-demand Dev build when run manually.

A failed simulator suite blocks normal IPA delivery. To request a private candidate after a failed full-suite run, explicitly enable `allow_failed_ui_tests_for_private_candidate`. The release title identifies the candidate and the run still reports the test failure. Swift contract failures and missing simulator results block packaging.
