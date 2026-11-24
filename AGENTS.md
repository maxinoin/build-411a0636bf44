# iOS build validation

Use the manual Build iOS workflow. IPA requests run the Swift contracts and the
full simulator regression suite on the exact source revision they package.
Deliver IPA files and filtered failure diagnostics through the private source
repository. See WORKFLOWS.md for the available inputs.

## Dependency broker

Run `python -m unittest discover -s tests -v` for maintenance changes. Keep
all source PR execution and package resolution isolated from broker credentials.
Only validated same-repository Dependabot branches may receive generated lock
commits. The updater token grants repository Contents write; protect the broker
workflow and never call merge APIs or update the default branch with it.
Keep public logs generic and test advisory failures, stale commits and alerts.
