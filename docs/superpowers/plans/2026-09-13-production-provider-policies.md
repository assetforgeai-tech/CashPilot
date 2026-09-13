# Production Provider Policies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make provider allocation and lifecycle policies production-ready while keeping Pawns isolated and EarnApp account/node health explicit.

**Architecture:** Preserve the existing provider registry and database lease primitives. Add only the missing shared capacity view and explicit provider-policy documentation/UI; keep Pawns `ip_used` masks provider-scoped and EarnApp health actions node-scoped. Validate with focused tests before live rollout.

**Tech Stack:** Python, FastAPI, SQLite, Jinja, vanilla JavaScript, pytest.

## Global Constraints

- Pawns/IPRoyal `ip_used` masks and replaces only its own proxy allocation.
- EarnApp `offline`, `usage_stalled`, and node `banned` signals are node-scoped; account suspension/auth failure is separate manual/account handling.
- Direct-only, proxy-only, and hybrid lanes never fall back across egress types.
- Runtime lease release does not release EarnApp sticky egress ownership.
- No credential or token value appears in API/UI output.

### Task 1: Provider policy contract

**Files:** `app/provider_runtime.py`, `app/provider_lifecycle.py`, `tests/test_provider_lifecycle_policy.py`.

- [x] Add explicit `policy_group` and `proxy_failure_scope` fields to `ProviderRuntime`, defaulting to the existing behavior.
- [x] Set IPRoyal to `policy_group="pawns"`, `proxy_failure_scope="provider"`; set EarnApp to `policy_group="earnapp"`, `proxy_failure_scope="node"`.
- [x] Assert lifecycle decisions cannot apply EarnApp usage actions to IPRoyal or other providers.
- [x] Run lifecycle regression tests.

### Task 2: Shared provider capacity summary

**Files:** `app/provider_accounts.py`, `app/main.py`, `app/static/js/app.js`, `app/templates/settings.html`, `tests/test_provider_topology_api.py`, `tests/test_earnapp_settings_ui.py`.

- [x] Extend `/api/admin/provider-account-pools` with secret-free proxy capacity values where database evidence exists.
- [x] Render concise per-provider rows with available / eligible labels; keep unknown values as `—` rather than zero.
- [x] Add regression tests for response shape and the no-secret invariant.
- [x] Run focused API/UI tests.

### Task 3: Settings sub-navigation

**Files:** `app/templates/settings.html`, `app/static/css/style.css`, `app/static/js/app.js`, `tests/test_earnapp_settings_ui.py`.

- [x] Keep the five anchors `Accounts`, `EarnApp input`, `Runtime`, `Collector`, and `Payment`.
- [x] Add sticky navigation, mobile wrapping, and keyboard-visible focus states without introducing a second routing system.
- [x] Verify navigation labels and responsive CSS with static tests.

### Task 4: Evidence and release gate

**Files:** `docs/evidence/provider-policy-production-readiness-2026-09-13.md`.

- [x] Record focused tests, full suite, Ruff, compileall, and `git diff --check`.
- [ ] Record live checks separately for Pawns isolation, EarnApp node health, direct/proxy/hybrid topology, DNS/IPv6/UDP, and worker reconciliation.
- [x] Leave production status `pending` until live evidence exists; do not infer it from unit tests.
