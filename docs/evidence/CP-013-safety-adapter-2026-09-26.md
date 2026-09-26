# CP-013 Safety Adapter Evidence

Date: 2026-09-26
Branch: `fix/cp013-safety-adapter-20260926`
Base: `2ce4d87af9957dd1d8a6d5b8a3bf272a2b7df358`

## Scope

This change connects generic diagnostic deployment to the worker-authoritative
egress probe. It does not deploy, restart, rotate, delete, or mutate any Azure
resource, worker, provider, proxy, wallet, lease, or production node.

## Contract

- Every generic deployed lane with running instances calls
  `/api/providers/egress-probe` before the lane is recorded.
- The probe result is compared with the active provider proxy lease and its
  expected exit IP.
- Missing probe, missing provider-instance authority, or missing expected
  egress is `verification_pending`; it is not guessed as a route failure.
- `probe_ok=false` is `route_failure` and fences the current diagnostic round.
- Active lease absence or proxy-id mismatch is `wrong_lease` and fences the
  current diagnostic round.
- Observed egress mismatch is `egress_mismatch` and fences the current
  diagnostic round.
- Existing deploy failure status is preserved when probe evidence is missing.
- No retry is introduced by this adapter.

## Verification

- Focused safety/round tests: PASS, 19 tests.
- Full test suite: PASS, `3661 passed, 7 skipped`.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS.
- `python -m compileall -q app tests`: PASS.
- `git diff --check`: PASS.
- Secret-pattern scan: no secret values found; only variable names and test
  fixtures matched.

## External state

- `origin/main` remained `2ce4d87af9957dd1d8a6d5b8a3bf272a2b7df358` during
  implementation.
- Release `v1.69.2` and its rollback manifest were not changed.
- Live gate remains CLOSED.
- No Azure, SSH, provider, proxy, wallet, lease, or production mutation.

## Follow-up gate

After PR/CI/merge, run a disposable diagnostic round only with a separately
approved scope. The adapter merge alone does not authorize full deployment or
production readiness.
