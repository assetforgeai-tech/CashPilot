# Pre-live baseline — 2026-09-10/11

## Scope

Read-only baseline for the CashPilot production-readiness gate. No live provider
node was deleted, recreated, rotated, released, or redeployed.

## Repository

- Branch: `docs/earnapp-production-closeout`
- Audited commit: `efe4ce1b282aaf00fa2f457bb5ff61658b39ac6b`
- PR #246: open; checks for its current remote HEAD are green (`test`, `build (strict)`, `ruff`, `Analyze`); deployment job skipped by workflow policy. Local audit fixes below are not yet committed/pushed, so they still require a new CI run.
- Existing user artifacts remain unmodified: `.tmp-doh-*`, `.tmp-mac-*`, `.tmp-reference-mac`, `.tmp-ubuntu-fixed2`.
- Audit changes: platform-safe `uvloop` dependency marker, compose pin update, this evidence and regression test.

## Verification

- Full pytest before audit fix: `2753 passed, 8 skipped, 2 failed`.
- Initial failures: both shipped compose files pinned `1.29` while the newest fork release was `1.32`.
- After fix: compose pin suite `22 passed`; security/auth/frontend subset `248 passed`; provider-network subset `30 passed`.
- Full `uv run pytest tests/ -q` reached 100%; the only failures were the stale compose pins above.
- Full `uv run pytest tests/ -q` after fixes: `2761 passed, 8 skipped`.
- Ruff source scan passes when user `.tmp-*` artifacts are excluded. The repository-wide scan still reports an old non-UTF8 archive and an unformatted user artifact; neither is source code.
- Windows dependency reproduction: `uv sync --dev` originally failed because `uvloop` was unconditional. The marker now excludes Windows; targeted contract tests pass.

## Browser gate

Chrome profile 40 could not be inspected through the desktop browser connector on
this run: `Codex auth token is unavailable`. Therefore the requested live UI
click/input/screenshot sweep remains unverified and must not be represented as
complete.

## Current decision

Code-level baseline is improved, but the pre-live gate remains open until PR #246
is merged/released, the UI sweep is captured, and provider network/runtime evidence
is completed.
