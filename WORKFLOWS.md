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


## Dependency maintenance

The dependency broker supports runtime, training and development locks. It
resolves related locks inside a credential-free, manifest-only uv container,
then updates only those locks on authenticated same-repository Dependabot PRs.
Set DEPENDENCY_UPDATE_TOKEN in this broker's Actions secrets with Contents
read/write on the private source repository only. If separate read/status
secrets are absent, also grant Pull requests read and Commit statuses read/write
to the updater token; the trusted orchestrator uses it for those API calls too.
Existing separate read/status credentials take precedence. No code calls the merge API.
Contents write is a repository-wide GitHub permission; trusted code restricts
writes to generated lockfiles on validated Dependabot branches. Restrict broker
write access because its maintainers can edit the workflow that uses the token.

Every three hours the broker checks new dependency PR commits; once per UTC day
it also audits main against current Python/npm advisory databases. Failures and
new advisories notify the configured Discord user/channel. Missing Copilot
reviews no longer block a passed-check review reminder. Notifications describe
AI review as pending where appropriate. Public output remains generic.

Merge this broker update before the private dependency split. It accepts legacy
branches without the new locks. Lock resolution is limited to registry packages
and allowlisted requirements includes; private PR scripts are never executed
with writer credentials. Missing writer permission is reported as a failed lock
refresh whenever related locks need a commit. Do not reuse release credentials.

Local regression check: `python -m unittest discover -s tests -v`.
Docker-based integration checks require Docker/WSL and are a separate gate.
