# Proxy Pool Lease And UI Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make new Proxy Pool leases fail closed on authoritative probe evidence, invalidate stale EarnApp qualification after an egress change, and make the large Proxy Pool usable and accessible without downloading the complete inventory.

**Architecture:** Ship two isolated UI-image releases. The first changes only candidate-selection SQL and regression tests; it never mutates existing assignments or provider runtime. The second adds a paginated read model/API plus responsive and accessible template behavior while leaving recheck, import, delete, export, and lease contracts intact.

**Tech Stack:** Python 3.12, FastAPI, SQLite/aiosqlite, Jinja2, browser JavaScript, pytest, Ruff, GitHub Actions, Docker.

## Global Constraints

- Do not modify protected provider implementations, worker code, provider identities, wallets, credentials, volumes, or active leases.
- Do not recreate or redeploy `cashpilot-worker`; its container identity and start time must remain unchanged.
- Release and redeploy only the UI component after each merged PR.
- Require `proxy_endpoints.status = 'alive'` and a non-empty authoritative `exit_ip` for every new legacy candidate or lease.
- For EarnApp, require the latest `CID_SET` evidence to refer to the current endpoint egress IP.
- Preserve current assignments and idempotent retrieval of an existing scoped lease.
- Use test-first red/green cycles and run the full verification suite before every PR.

---

### Task 1: Document The Shared Lease Impact Map

**Files:**
- Create: `docs/research/proxy-lease-safety-impact-map.md`

**Interfaces:**
- Consumes: `database.lease_proxy_for_worker(worker_id, provider_slug=None)` and `database.find_available_proxy_for_worker(worker_id, provider_slug=None)` call sites.
- Produces: a durable statement of affected callers, protected state, release boundary, and live verification queries.

- [ ] **Step 1: Trace every production caller**

Run: `rg -n "lease_proxy_for_worker\\(|find_available_proxy_for_worker\\(" app`

Expected: only `app/main.py`, `app/routers/proxies.py`, and the two definitions in `app/database.py`.

- [ ] **Step 2: Record the safety boundary**

Document that the change affects only selection of a new candidate; it does not delete, release, rotate, or rewrite an existing assignment by itself. Record each caller and the behavior when no verified candidate exists.

- [ ] **Step 3: Verify the impact document names every caller**

Run: `rg -n "app/main.py|app/routers/proxies.py|lease_proxy_for_worker|find_available_proxy_for_worker" docs/research/proxy-lease-safety-impact-map.md`

Expected: both functions and all caller paths are present.

### Task 2: Make Legacy Candidate Selection Fail Closed

**Files:**
- Modify: `app/database.py`
- Test: `tests/test_proxy_routes.py`

**Interfaces:**
- Consumes: endpoint `status` and `exit_ip` written by the generic probe.
- Produces: a new legacy lease/candidate only when `lower(status) = 'alive'` and `trim(exit_ip) != ''`.

- [ ] **Step 1: Write failing regression tests**

Add one test proving `lease_proxy_for_worker()` skips `unknown` and missing-egress rows, and one test proving `find_available_proxy_for_worker()` does the same. Each test seeds an invalid row before one verified row and asserts the verified row is selected.

- [ ] **Step 2: Run the focused tests and observe RED**

Run: `python -m pytest tests/test_proxy_routes.py -k "legacy_lease_requires_authoritative_probe or legacy_candidate_requires_authoritative_probe" -q`

Expected: both tests fail because the first unverified endpoint is returned.

- [ ] **Step 3: Apply the minimal SQL predicate change**

Replace permissive status and empty-egress branches in both legacy selectors with:

```sql
lower(coalesce(pe.status, 'unknown')) = 'alive'
AND trim(coalesce(pe.exit_ip, '')) != ''
```

Keep duplicate, provider-mask, scoped-lease, existing-egress, ordering, transaction, and assignment-version behavior unchanged.

- [ ] **Step 4: Run focused tests and observe GREEN**

Run: `python -m pytest tests/test_proxy_routes.py -k "proxy_lease or proxy_mask or proxy_rotation" -q`

Expected: all selected tests pass.

### Task 3: Bind EarnApp Qualification To The Current Egress

**Files:**
- Modify: `app/database.py`
- Test: `tests/test_proxy_routes.py`

**Interfaces:**
- Consumes: latest `proxy_probe_results` row for profile `earnapp_wss` and current `proxy_endpoints.exit_ip`.
- Produces: an EarnApp scoped lease only when the latest eligible `CID_SET` row has the same non-empty egress IP as the endpoint.

- [ ] **Step 1: Write the failing stale-evidence test**

Seed a generic probe and eligible EarnApp probe for egress A, then a later generic probe changing the endpoint to egress B. Assert `lease_proxy_for_provider_instance('earnapp', ...)` returns `None` until a new eligible EarnApp probe for egress B is saved.

- [ ] **Step 2: Run the focused test and observe RED**

Run: `python -m pytest tests/test_proxy_routes.py -k "earnapp_lease_rejects_stale_egress" -q`

Expected: failure because the stale `CID_SET` still leases the endpoint.

- [ ] **Step 3: Add the egress equality guard**

Add this condition to the latest eligible EarnApp `EXISTS` clause and to duplicate canonical ranking:

```sql
trim(coalesce(earnapp.exit_ip, '')) != ''
AND earnapp.exit_ip = pe.exit_ip
```

Use the equivalent probe alias in canonical ranking. Do not delete historical probe rows.

- [ ] **Step 4: Run the focused tests and observe GREEN**

Run: `python -m pytest tests/test_proxy_routes.py -k "earnapp or duplicate or provider_scoped_lease" -q`

Expected: all selected tests pass.

### Task 4: Verify And Ship The Lease Safety PR

**Files:**
- Verify: `app/database.py`
- Verify: `tests/test_proxy_routes.py`
- Verify: `docs/research/proxy-lease-safety-impact-map.md`

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: merged backend safety PR and UI image release without worker recreation.

- [ ] **Step 1: Run complete local gates**

Run:

```bash
python -m pytest -q
python -m ruff check .
python -m compileall -q app tests
git diff --check
```

Expected: zero test failures, zero lint errors, successful compilation, and no diff whitespace errors.

- [ ] **Step 2: Commit, push, and open the PR**

Commit only the database predicates, regression tests, impact map, and this implementation plan. Push the branch and create a PR that includes the impact map and states that existing leases are preserved.

- [ ] **Step 3: Wait for required CI and merge**

Expected: Tests, Lint, CodeQL, Catalog Check, and release-relevant checks pass before merge.

- [ ] **Step 4: Verify the UI image and deploy only `cashpilot-ui`**

Resolve the new release tag and registry digest, recreate only the UI container with its existing environment, network, mounts, ports, labels, and restart policy, and verify the worker container ID/start time did not change.

- [ ] **Step 5: Run live read-only lease safety checks**

Against a copy of the live SQLite database, verify no new legacy candidate can be selected from an unknown/dead/missing-egress row and no EarnApp-eligible row has a probe egress different from the current endpoint egress. Do not create a live lease.

### Task 5: Add A Paginated Proxy Pool Read Model

**Files:**
- Modify: `app/database.py`
- Modify: `app/routers/proxies.py`
- Test: `tests/test_proxy_routes.py`

**Interfaces:**
- Consumes: page, page size, search, provider, location, IP type, EarnApp state, duplicate state, sort key, and sort direction.
- Produces: `{items, page, page_size, total, pages, counts, filters}` with no credentials and a bounded item payload.

- [ ] **Step 1: Write failing API tests**

Test that `/api/proxy-pool?page=2&page_size=20` returns a bounded envelope, that search/filter/sort happen before pagination, that invalid sort keys are rejected or mapped to a safe default, and that response items omit username/password.

- [ ] **Step 2: Run focused tests and observe RED**

Run: `python -m pytest tests/test_proxy_routes.py -k "proxy_pool_page" -q`

Expected: failure because the endpoint still returns the complete list.

- [ ] **Step 3: Implement parameterized server-side pagination**

Add a dedicated database page query with a fixed allowlist of SQL sort expressions. Reuse the current joined read model, apply parameterized filters, calculate total and aggregate counts separately, and cap page size at 100. Keep `list_proxy_pool()` for internal full-inventory recheck jobs.

- [ ] **Step 4: Run focused tests and observe GREEN**

Run: `python -m pytest tests/test_proxy_routes.py -k "proxy_pool_page or proxy_pool_export or proxy_pool_recheck" -q`

Expected: all selected tests pass.

### Task 6: Make The Proxy Pool Responsive And Accessible

**Files:**
- Modify: `app/templates/proxy_pool.html`
- Test: `tests/test_frontend_wiring.py`

**Interfaces:**
- Consumes: paginated API envelope from Task 5.
- Produces: responsive import controls, labeled search/file/row-selection inputs, server-driven filtering/sorting/paging, and a page-status announcement.

- [ ] **Step 1: Write failing static frontend tests**

Assert the search and file inputs have labels, row checkboxes render an endpoint-specific `aria-label`, the import grid has a mobile breakpoint, and JavaScript requests the current page/filter/sort instead of slicing a complete inventory.

- [ ] **Step 2: Run focused tests and observe RED**

Run: `python -m pytest tests/test_frontend_wiring.py -k "proxy_pool" -q`

Expected: failures for missing labels, fixed import layout, and client-only pagination.

- [ ] **Step 3: Implement the minimal template changes**

Use semantic labels (visually hidden where appropriate), a `.pool-import-grid` class with a one-column mobile breakpoint, and an `AbortController`/request sequence guard so rapid filter changes cannot render stale pages. Keep horizontal table scrolling because thirteen operational columns cannot be made legible at 375px without hiding evidence.

- [ ] **Step 4: Run focused tests and observe GREEN**

Run: `python -m pytest tests/test_frontend_wiring.py -k "proxy_pool" -q`

Expected: all selected tests pass.

### Task 7: Verify And Ship The Proxy Pool UI PR

**Files:**
- Verify: `app/database.py`
- Verify: `app/routers/proxies.py`
- Verify: `app/templates/proxy_pool.html`
- Verify: `tests/test_proxy_routes.py`
- Verify: `tests/test_frontend_wiring.py`

**Interfaces:**
- Consumes: Tasks 5-6.
- Produces: merged UI PR, UI-only release/deploy, desktop/mobile evidence, and final Proxy Pool audit.

- [ ] **Step 1: Run complete local gates**

Run the same pytest, Ruff, compileall, and diff checks from Task 4.

- [ ] **Step 2: Verify real browser behavior**

Use Playwright at desktop width and 375px width. Confirm body width does not exceed viewport, import controls are usable, labels are discoverable, pagination changes the server request, filters reset to page 1, sorting is keyboard operable, and API payload is bounded.

- [ ] **Step 3: Commit, push, PR, CI, and merge**

The PR must state that only the Proxy Pool read/UI surfaces changed and that worker/provider runtime remains untouched.

- [ ] **Step 4: Release and redeploy only `cashpilot-ui`**

Verify the new digest, preserve all UI container runtime settings, and prove the worker container ID/start time is unchanged.

- [ ] **Step 5: Run the final live audit sweep**

Capture inventory, generic live/dead, authoritative egress, EarnApp states, duplicate rows, canonical generic usable, EarnApp leaseable, country/type coverage, metadata pending, active legacy/scoped leases, API payload/time, mobile body width, DB integrity, scheduler state, UI health, and worker identity. List any remaining gap and recommend the next smallest safe task.
