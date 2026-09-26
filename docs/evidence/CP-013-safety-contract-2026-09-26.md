# CP-013 safety-contract follow-up — 2026-09-26

## Scope

Code-only pre-live gate. No Azure, SSH, VPS, provider, proxy, wallet, lease,
account-pool, or production mutation. CP-013 remains `IN_PROGRESS`; live gate
remains closed.

## Changes

- Added an explicit, redacted fatal-safety classifier for identity mismatch,
  wrong wallet, wrong lease, direct/proxy fallback, egress mismatch, route
  failure, and DNS failure.
- A typed `RolloutSafetyViolation` stops the current diagnostic round. An
  unstructured provider exception remains an ordinary lane failure, preserving
  the existing collect-the-round behavior and avoiding message-based guesses.
- A structured `result["safety"]` signal stops the round; unknown positive
  safety signals fail closed as `unclassified_safety`.
- Fatal rounds record a safe error code and remain `running`, so heartbeat or
  restart cannot retry them before operator reconciliation.
- Added read-only provider/slot reconciliation to the plan endpoint. It reports
  desired/eligible/running, missing, unexpected, duplicate, mismatched, and
  blocked slots without leasing or deploying anything.

## Verification

- RED observed: new safety/reconciliation tests failed before implementation.
- Focused safety/round/provider regression: `109 passed` across the CP-013,
  auto-deploy, slot, topology, and network suites.
- Full suite: `3651 passed, 7 skipped`.
- `uv run ruff check` passed after formatting.
- `uv run ruff format --check` passed after formatting.
- `python -m compileall -q app tests` passed.
- `git diff --check` passed.

## Gate status

Live gate remains **CLOSED**. This change does not authorize full-worker
diagnostic deployment. Provider adapters still need verified structured safety
signals and an operator-approved release/worker/resource snapshot before live
entry.
