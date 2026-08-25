# EarnApp Account Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an isolated EarnApp Account Pool, read-only account collector, HTTPS Chrome token importer, and logical-node recovery that holds the original proxy for exactly one hour before safely returning it to the pool.

**Architecture:** Preserve the existing provider-instance proxy lease contract for every shipped provider. EarnApp adds its own account, logical-node, control-route, recovery, and replacement-ticket tables; an active/recovery-held EarnApp route remains visible to the shared proxy allocator only as an exclusion. Worker replacement reuses account and device identity, prefers the original proxy while it is healthy and available, and falls back to a new eligible residential proxy without changing the account binding.

**Tech Stack:** FastAPI, Pydantic, SQLite/aiosqlite, Fernet, httpx with HTTP/SOCKS proxy routing, Jinja/vanilla JavaScript, Chrome Manifest V3, pytest.

## Global Constraints

- `RECOVERY_HOLD_SECONDS` is exactly `3600` seconds and starts after the existing 15-minute stale-worker recovery threshold.
- EarnApp never shares a canonical egress IP between two active/control/recovery-held EarnApp routes.
- Account assignment, logical node identity, and remote device identity survive worker loss; no automatic remote unlink/delete is allowed.
- A new worker may inherit another worker's nodes only through a one-time replacement ticket; the original worker uses its persisted `client_id` recovery path.
- Account distribution is least-assigned first with no artificial maximum; offline-recoverable nodes still count toward balance.
- Collector traffic must use a proxy already belonging to the account, or a dedicated account-control proxy before its first node exists.
- Account deletion is allowed only for `ACCOUNT_LOCKED`; it retires local nodes, releases local routes, and removes encrypted credentials without deleting the remote EarnApp account/device.
- Only EarnApp requires residential proxies in this change. No lease predicate, runtime, catalog, credential, or deployment behavior of a protected provider may change.
- All Chrome provider imports use one allowlisted HTTPS `4gmt.com` CashPilot endpoint; the legacy plaintext HTTP/IP destination is removed. Credentials are never returned by list APIs or written to logs.
- This plan does not implement platform/device-identity spoofing or automatic Google/Apple password, MFA, OTP, or CAPTCHA handling.

---

### Task 1: EarnApp persistence and token metadata

**Files:**
- Create: `app/earnapp_accounts.py`
- Modify: `app/database.py`
- Test: `tests/test_earnapp_account_pool.py`

- [x] Write failing tests for encrypted credential import, Google/Apple auth methods, JWT/cookie expiry metadata, masked list output, least-assigned account selection, and locked-only deletion.
- [x] Run the focused tests and confirm they fail because the EarnApp tables/helpers do not exist.
- [x] Add idempotent schema and minimal database/domain helpers.
- [x] Run the focused tests until green.

### Task 2: One-hour recovery hold and replacement tickets

**Files:**
- Create: `app/earnapp_recovery.py`
- Modify: `app/database.py`
- Modify: `app/main.py`
- Test: `tests/test_earnapp_recovery.py`

- [x] Write failing tests for the 15-minute stale threshold, exact one-hour hold, proxy exclusivity during hold, affinity after release, same-worker recovery, one-time replacement tickets, generation conflicts, and fallback to a new proxy.
- [x] Run the focused tests and confirm expected missing-contract failures.
- [x] Implement the recovery state machine and connect it only to the existing stale-worker/heartbeat paths.
- [x] Run the focused tests until green.

### Task 3: Account control routes and read-only collector

**Files:**
- Create: `app/collectors/earnapp.py`
- Create: `app/earnapp_collection.py`
- Modify: `app/database.py`
- Test: `tests/test_earnapp_collector.py`

- [x] Write failing fixtures/tests for XSRF rotation, balance/lifetime/device schema normalization, online/offline statuses, proxy URL construction, auth-vs-route failure classification, and control-route transfer to the first node.
- [x] Run focused tests and verify RED.
- [x] Implement proxy-routed collection and sanitized account snapshots without registering EarnApp in the legacy one-collector-per-slug cache.
- [x] Run focused tests until green.

### Task 4: Owner API and dashboard

**Files:**
- Create: `app/routers/earnapp_accounts.py`
- Modify: `app/main.py`
- Modify: `app/templates/settings.html`
- Modify: `app/static/js/app.js`
- Modify: `app/static/css/style.css`
- Test: `tests/test_earnapp_account_routes.py`
- Test: `tests/test_frontend_wiring.py`

- [x] Write failing route/UI tests for masked account lists, manual import/update, locked-only double-confirmed deletion, replacement tickets, collector summaries, proxy capacity, recovery countdown, and prominent token warnings.
- [x] Run focused tests and verify RED.
- [x] Implement owner-only routes and the EarnApp Account Pool UI without exposing credentials.
- [x] Run focused tests until green.

### Task 5: Chrome profile importer and automatic refresh sync

**Files:**
- Modify: `contrib/chrome-provider-importer/manifest.json`
- Create: `contrib/chrome-provider-importer/background.js`
- Modify: `contrib/chrome-provider-importer/popup.html`
- Modify: `contrib/chrome-provider-importer/popup.js`
- Modify: `contrib/chrome-provider-importer/README.md`
- Test: `tests/test_chrome_provider_importer.py`

- [x] Write failing tests for exact EarnApp cookie allowlist, Google/Apple method, JWT `exp`, Chrome cookie expiration, one-profile/one-account binding, explicit first import, background updates only for imported accounts, and HTTPS-only `4gmt.com` sync for all provider imports.
- [x] Run focused tests and verify RED.
- [x] Implement the minimal Manifest V3 cookie watcher and popup flow; never access Google/Apple cookies and never print values.
- [x] Run focused tests until green.

### Task 6: Regression boundary and documentation

**Files:**
- Modify: `docs/ACTIVE_CONTEXT.md`
- Modify: `docs/research/repo-github-understanding.md`

- [x] Run EarnApp/proxy/worker focused tests and Ruff on changed Python files.
- [x] Run the full non-live test suite and frontend wiring checks.
- [x] Inspect `git diff --check`, secret scans, protected-provider file boundaries, and worktree status.
- [x] Record the exact implemented scope, HTTPS hostname requirement, one-hour recovery contract, and remaining official runtime/live-canary work.

### Task 7: Final pre-PR race and observability audit

- [x] Add RED regressions for original-worker return versus an outstanding
  replacement ticket, missing target workers, popup URL validation, cookie
  debounce alarm isolation, and distinct-egress capacity.
- [x] Make ticket creation, heartbeat recovery cancellation, and claim state
  guards transactional under the EarnApp lock.
- [x] Count capacity by canonical egress and isolate recurring/debounce Chrome
  alarms; run the new regressions to GREEN.

Verification evidence: focused suite `283 passed`; full non-live suite
`1812 passed, 8 skipped`; Ruff lint, changed-file Ruff format, compileall,
JavaScript parse, deploy-baseline and `git diff --check` pass. The only
repository-wide Ruff format failure is the pre-existing unchanged file
`docs/superpowers/plans/2026-08-25-proxy-import-protocol.md`.
