# EarnApp Production Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Finish the remaining production policies without changing accepted provider runtimes.

**Architecture:** Add durable EarnApp egress ownership beside active leases; active lease release remains reversible while account ownership persists until explicit account deletion. Add PayPal assignment and shared read-only capacity/account views using existing database and router patterns. Audit provider network contracts before any worker rollout.

**Tech Stack:** Python, FastAPI, SQLite/aiosqlite, static JavaScript, pytest.

## Global Constraints

- Preserve accepted EarnApp Docker runtime and fail-closed proxy behavior.
- Do not alter protected/non-EarnApp provider runtime behavior during policy work.
- Account deletion remains explicit and requires existing cleanup acknowledgement.
- Runtime lease release never releases EarnApp egress ownership.
- No credentials, tokens, cookies, or SSH keys in logs, fixtures, or responses.
- No live redeploy until tests, audit matrix, and reconciliation evidence pass.

### Task 1: Sticky egress ownership (implementation complete; verification complete)

**Files:**
- Modify: `app/database.py`
- Modify: `tests/test_earnapp_account_pool.py`

**Deliverable:** unique durable ownership by `(account_id, egress_ip)` and allocation exclusion for owned egress belonging to another account; account deletion releases ownership.

- [x] Write failing tests for release/reallocate and same-account reuse.
- [x] Run targeted tests and confirm failure because ownership table/queries are absent.
- [x] Add idempotent migration/table/indexes and minimal helper queries.
- [x] Apply ownership checks to EarnApp node and control-proxy allocation.
- [x] Release ownership only inside successful locked-account deletion transaction.
- [x] Run targeted then full database/account tests.

### Task 2: EarnApp payment UI (implementation complete)

**Files:**
- Modify: `app/static/js/app.js`
- Modify: `tests/test_earnapp_settings_ui.py`

Replace payment `window.prompt` calls with an inline modal/select using existing payment API; preserve masked display and confirmation behavior.

### Task 3: PayPal pool (foundation complete; automatic default enabled during scheduled collection)

**Files:**
- Modify: `app/database.py`
- Modify: `app/routers/earnapp_accounts.py`
- Modify: `app/static/js/app.js`
- Create: `tests/test_earnapp_paypal_pool.py`

Add encrypted destination records, fixed account assignment, default auto-redeem, permanent quarantine after account deletion, and operator-visible status.

- Automatic setup runs only for an unconfigured account after a successful collection; existing payment choices are never overwritten.

### Task 4: Unified capacity and account views (EarnApp/provider capacity complete; common account abstraction pending)

**Files:**
- Modify: `app/database.py`
- Modify: `app/routers/proxies.py`
- Modify: `app/static/js/app.js`
- Create: `tests/test_provider_capacity.py`

Expose concise provider-group totals: eligible, assigned, available, sticky-owned, masked. Keep provider-specific adapters where required and paginate account lists.

### Task 5: Heartbeat/rotation policy and reconciliation (EarnApp policy complete; read-only reconciliation complete)

**Files:**
- Modify: `app/earnapp_lifecycle.py`
- Modify: `app/main.py`
- Modify: `app/database.py`
- Create: `tests/test_provider_lifecycle_policy.py`
- Create: `tests/test_reconciliation.py`

Normalize restart/offline, banned/replace, token retry, and provider-group rotation decisions. Add read-only reconciliation report comparing DB rows, heartbeat inventory, and Docker inventory; alert first, never delete automatically.

### Task 6: Provider-wide proxy leak audit (source matrix and drift reporting complete; live proof pending)

**Files:**
- Create: `docs/evidence/provider-proxy-leak-audit.md`
- Create: `tests/test_provider_network_contracts.py`

Inventory every provider runtime. Verify direct IPv4/IPv6, DNS/DoH, UDP/WebRTC, bypass process, and reboot persistence. Mark unknown as unverified; do not infer from EarnApp evidence.

- [x] Add read-only provider network reconciliation for proxy-only instances missing a managed sidecar.
- [x] Record the live Wipter direct-egress finding; defer migration until a canary/rollback plan is approved.

### Task 7: Token refresh and rollout (token refresh/import complete; rollout pending)

**Files:**
- Inspect/modify: EarnApp token import/extension integration paths only
- Create: `docs/evidence/earnapp-token-refresh-audit.md`

Validate expiry extraction, manual-login-gated auto-import, retry on expiry, and alerting. Then run full tests, release, and controlled worker rollout only after compatibility checks.

## Verification gates

- Targeted tests fail before each implementation and pass after.
- Full suite remains green.
- Migration is idempotent on fresh and upgraded databases.
- No unapproved live provider changes.
- Release images and worker versions are independently verified in registry.
