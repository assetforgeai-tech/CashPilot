# EarnApp Proxy Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add isolated EarnApp proxy qualification and leasing, authoritative egress metadata, duplicate-egress controls, duplicate exports, and a twice-confirmed full Proxy Pool deletion without changing any provider runtime.

**Architecture:** Keep the existing generic worker-level proxy assignment contract intact. Add append-only probe evidence, endpoint intelligence metadata, duplicate canonicalization, and provider-instance leases in new database structures; EarnApp consumes only `CID_SET` proxies through the new scoped lease contract. Port the supplied WSS probe to a dependency-free Python module so the UI image does not gain Node/npm.

**Tech Stack:** FastAPI, Pydantic, SQLite/aiosqlite, asyncio streams/TLS/WebSocket framing, Jinja/vanilla JavaScript, pytest.

## Global Constraints

- Do not edit provider catalog/runtime/collector code or redeploy any service.
- Existing worker-level assignments and running providers remain authoritative and are never rotated because of duplicate detection.
- Only EarnApp `CID_SET` is eligible; `BLACKLIST`, `DECLINE`, timeout, and transport errors are ineligible.
- Duplicate egress is recorded globally and excluded from every new lease while existing assignments remain untouched.
- `Delete all` deletes every proxy endpoint and related pool state only after two confirmations; it does not delete proxy-provider credentials/configuration.
- Raw credential exports are owner-only and never included in normal dashboard JSON.

---

### Task 1: Database contracts and migration

**Files:**
- Modify: `app/database.py`
- Test: `tests/test_proxy_routes.py`

- [x] Write failing migration and database behavior tests for metadata fields, append-only probe evidence, import batches, duplicate canonicalization, scoped leases, global new-lease uniqueness, and full pool deletion.
- [x] Run the focused tests and confirm failures describe missing schema/functions.
- [x] Add idempotent schema migration and minimal database functions.
- [x] Run the focused tests until green.

### Task 2: EarnApp WSS and IP intelligence probes

**Files:**
- Create: `app/proxy_probe_profiles/__init__.py`
- Create: `app/proxy_probe_profiles/earnapp.py`
- Create: `app/proxy_intelligence.py`
- Test: `tests/test_earnapp_proxy_probe.py`

- [x] Write failing tests for verdict mapping, `tunnel_init` response shape, WebSocket frames, metadata normalization, and IP-type precedence.
- [x] Run the tests and confirm the modules are missing.
- [x] Implement the supplied EarnApp protocol in isolated Python code and merge `ipwho.is` country data with `ipapi.is` quality flags.
- [x] Run the focused tests until green.

### Task 3: API orchestration and exports

**Files:**
- Modify: `app/routers/proxies.py`
- Test: `tests/test_proxy_routes.py`

- [x] Write failing route/orchestration tests for generic metadata refresh, EarnApp recheck, scoped lease/release, duplicate masked/raw export, accurate imported IDs, and double-confirmed delete-all.
- [x] Run the focused tests and confirm expected failures.
- [x] Implement the minimal owner-only endpoints and orchestration.
- [x] Run the focused tests until green.

### Task 4: Proxy Pool dashboard

**Files:**
- Modify: `app/templates/proxy_pool.html`
- Test: `tests/test_frontend_wiring.py`

- [x] Write failing wiring tests for country/type/live evidence/EarnApp/duplicate columns and filters, duplicate exports, and two sequential delete-all confirmations.
- [x] Run the focused test and confirm failure.
- [x] Upgrade the table, filters, badges, controls, responsive labels, and destructive feedback while preserving existing controls.
- [x] Run the focused test until green.

### Task 5: Regression verification and documentation

**Files:**
- Modify: `docs/ACTIVE_CONTEXT.md`
- Modify: `docs/research/repo-github-understanding.md` if present and relevant

- [x] Run proxy-focused tests and Ruff on changed Python files.
- [x] Run the full non-live test suite.
- [x] Inspect `git diff --check`, the provider-file diff boundary, and worktree status.
- [x] Record verified behavior and explicitly state that EarnApp runtime/provider implementation remains out of scope.
