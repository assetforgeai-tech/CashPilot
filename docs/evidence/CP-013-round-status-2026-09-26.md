# CP-013 generic round outcome evidence — 2026-09-26

## Scope

Code-only follow-up. No Azure, SSH, VPS, provider, proxy, wallet, lease,
account-pool, or production mutation.

## Root cause

`_auto_deploy_one` discarded the `api_deploy` response. The diagnostic round
therefore recorded every generic provider lane as `started`, including
`pending_capacity`, empty, or failed result payloads.

## Fix

- `_auto_deploy_one` now returns the deploy response.
- Generic round dispatch classifies `pending`, `failed`, and `started` from the
  redacted response shape.
- `started` requires deployed/running status plus instance/running evidence.
- Malformed or empty responses fail closed as `pending`.
- Existing ordinary-failure continuation and explicit-generation fencing remain
  unchanged.

## Verification

- Focused regression: `16 passed` (`uv run pytest tests/test_cp013_round_ledger.py -q`).
- Aggregate regression: `109 passed` across the CP-013 auto-deploy policy suites.
- Full suite: `3640 passed, 7 skipped` (`uv run pytest -q`).
- Ruff check: passed.
- Ruff format check: passed after formatting `app/main.py` and this test module.
- Python compileall: passed.
- Git diff check: passed.
- New matrix covers pending capacity, partial pending, failed, running, empty,
  and malformed responses.
- No live or production mutation.

## Gate status

Live gate remains **CLOSED**. Slot-level inventory/reconciliation, provider
ordering/manual exclusions, fatal safety-error classification, pinned release
backup/rollback, and exact live resource approval remain required.
