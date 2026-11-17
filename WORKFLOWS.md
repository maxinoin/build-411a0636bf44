# iOS operations

All builds are manual. The public broker reads the private shared `codex/ipa-queue` revision.

| Operation | Inputs | Validation |
| --- | --- | --- |
| Swift contracts only | deliver_private_ipa=false, run_ui_tests=false | Independent Swift checks in parallel |
| Route screenshot | visual_audit=true, visual_route_only=true, deliver_private_ipa=false | Build and launch the app, then six screenshots |
| Focused tests | deliver_private_ipa=false, run_ui_tests=true, test_suite=picker or sheets | Swift contracts plus selected simulator tests |
| Full tests | deliver_private_ipa=false, run_ui_tests=true, test_suite=full | Swift contracts plus full simulator suite |
| IPA | deliver_private_ipa=true | Swift contracts and full simulator suite must pass before packaging |

Scripts live in `scripts/ios`. Each run checks out the exact public workflow revision. Simulator test products are compiled once and reused by test-without-building. Device Release products require a separate compilation.

Dependency cache assets live exclusively in private KnightRoute prereleases tagged `ios-dependencies-v1-*`. Keys include the project specification, Xcode version, architecture and cache schema. Only downloaded Swift packages and XcodeGen are cached; app source, credentials, data and DerivedData are excluded. Delete these private cache releases to clear the cache. Missing caches resolve dependencies normally. Saving a cache is best effort; tests and builds still decide success.

Preview, test-only and IPA operations use separate concurrency groups. Backend checks stay on the developer PC. A preview is not a regression-suite pass. Test failures block IPA delivery. The private legacy build entry points users to this broker.
