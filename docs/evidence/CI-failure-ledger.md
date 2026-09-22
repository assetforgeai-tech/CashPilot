# CI Failure Ledger

Authoritative record for failures observed during repository, pull-request, CI, and release sweeps.

## Rules

- Inspect failed logs before any rerun.
- Classify the root cause; never use a blind rerun.
- After every push, PR update, merge, or release, inspect every job, including non-required jobs.
- Keep historical failures. Mark them superseded only when replacement evidence passes.
- Do not claim a green release while an unexplained failure remains.

## Entries

| Date (UTC) | Run | Commit/PR | Job | Root cause | Category | Fix/replacement | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-09-22 | [35754105957](https://github.com/assetforgeai-tech/CashPilot/actions/runs/35754105957) | `2c848cd` / main | Tests | Compose files pinned `1.63`; newest released series was `1.64`. | release pin drift | PR #481 updated both compose files; post-merge Tests run `35755500062` passed. | superseded |
| 2026-09-22 | [35754106193](https://github.com/assetforgeai-tech/CashPilot/actions/runs/35754106193) | `2c848cd` / main | Auto Release | Release gate reused the same stale compose pins, so verification failed before build/publish. | release sequencing | PR #481 updated both compose files; post-merge CI passed. | superseded |

## Current gate

At the last sweep, `origin/main` commit `43acafbf1821820215ae45a2337dccdee1cf0823` passed Tests, CodeQL, Lint, and Catalog Check. Open PRs and pending canary checks remain tracked by the coordinator.
