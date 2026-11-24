# iOS operations

All builds are manual. The public broker reads the private shared `codex/ipa-queue` revision.

| Operation | Inputs | Validation |
| --- | --- | --- |
| Swift contracts only | deliver_private_ipa=false, run_ui_tests=false | Independent Swift checks in parallel |
| Focused tests | deliver_private_ipa=false, run_ui_tests=true, test_suite=picker, sheets, startup, map, gestures or ownership | Swift contracts plus selected simulator tests |
| Full tests | deliver_private_ipa=false, run_ui_tests=true, test_suite=full | Five parallel macOS shards; all five must pass |
| IPA, tested | deliver_private_ipa=true, run_ui_tests=true | Five parallel macOS shards; packaging starts only after the full suite passes |
| IPA, manual test build | deliver_private_ipa=true, run_ui_tests=false | UI tests are skipped; release is labeled with the sheet style and test status |

Scripts live in `scripts/ios`. Each run checks out the exact public workflow revision. The full suite splits into map, sheet visuals, gesture ownership, gestures/settings, and startup/route picker shards. Each shard runs on its own Mac runner with one simulator; focused suites use one Mac runner with two simulator workers. Device Release products require a separate compilation.

Dependency cache assets live exclusively in private KnightRoute prereleases tagged `ios-dependencies-v1-*`. Keys include the project specification, Xcode version, architecture and cache schema. Only downloaded Swift packages are cached; app source, credentials, data and DerivedData are excluded. Delete these private cache releases to clear the cache. Missing caches resolve dependencies normally. Saving a cache is best effort; tests and builds still decide success.

Test-only and IPA operations use separate concurrency groups. Backend checks stay on the developer PC. The private legacy build entry points users to this broker.

## IPA delivery

One dispatch builds an unsigned IPA for a private release. Choose `sheet_style` to build the accent-rail/gray-divider or colored-divider-only variant. Set `run_ui_tests=false` when creating an IPA for manual testing; the release records that simulator UI tests were skipped. The `private_source_sha` input optionally selects a specific commit. With the input empty, the broker resolves the current queue commit.

A failed simulator suite blocks normal IPA delivery. To request a private candidate after a failed full-suite run, explicitly enable `allow_failed_ui_tests_for_private_candidate`. The release title identifies the candidate and the run still reports the test failure. Swift contract failures and missing simulator results block packaging.
