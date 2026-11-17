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

## Required visual review

Visible feature work includes screenshot capture and actual image inspection by the working Codex chat. The preview upload writes capture-index.json with source revision, run provenance and screenshot archive hashes. After viewing all indexed images, record the review using `python scripts/ios/visual_review.py record --tag ios-visual-audit-RUN-ATTEMPT --reviewer Codex --scope "screens and states inspected" --notes "findings and corrections" --reviewed-image "archive.zip:path/image.png"` (repeat the image argument for every image). Set PRIVATE_SOURCE_REPOSITORY and GH_TOKEN for the private repository. This command records a review; it does not inspect images itself.

Dispatch the IPA with `reviewed_preview` set to that tag. Missing or stale evidence blocks the run in queue resolution before a Mac is allocated. Any app commit change needs new screenshots and review. Preview and test-only operations do not require prior review. Existing full-suite gates still apply.
