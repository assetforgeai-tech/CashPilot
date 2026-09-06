# Proxy Import Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an operator import proxies as `Auto`, `HTTP`, or `SOCKS5` while preserving automatic protocol recovery for every later operational recheck.

**Architecture:** Add a request-scoped `protocol_mode` that controls parsing and only the generic check launched by that import. Forced modes persist the operator-selected protocol on imported rows and probe only that protocol initially; `auto` preserves explicit schemes and the existing SOCKS5-then-HTTP detection order. Scheduled/manual rechecks keep their current default auto-detection behavior, so no database migration, provider change, lease change, sidecar change, or worker release is required.

**Tech Stack:** Python 3.14, FastAPI, Pydantic, Jinja2, browser JavaScript, pytest, Ruff, Playwright, GitHub Actions, Docker.

## Global Constraints

- Do not import, recheck, delete, rotate, lease, release, or edit any live Proxy Pool row during development or verification.
- Do not modify provider catalog/runtime/collector code, worker code, proxy lease selection, sidecars, credentials, wallets, identities, volumes, or active assignments.
- Do not recreate or redeploy `cashpilot-worker`; release and redeploy only `cashpilot-ui`.
- Keep `Auto` as the default and preserve the current SOCKS5-then-HTTP probe order.
- Treat `HTTP` and `SOCKS5` as authoritative only for the import's initial generic check; later operational rechecks remain auto-recovery checks.
- Do not normalize live `VN`/`Viet Nam` rows in this change. Record the impact map only.
- Use test-first red/green cycles and fresh verification evidence before commit, PR, merge, release, deploy, or completion claims.

---

### Task 1: Record The Country-Label Impact Boundary

**Files:**
- Create: `docs/research/proxy-pool-country-label-impact-map.md`

**Interfaces:**
- Consumes: `app.proxy_intelligence`, proxy intelligence persistence, paginated Proxy Pool reads, filters, exports, and lease queries.
- Produces: a read-only map proving which surfaces would be affected by a future `VN`/`Viet Nam` canonicalization and which protected contracts are independent.

- [ ] **Step 1: Trace country evidence and consumers**

Run:

```powershell
rg -n "country_code|country_name|display_location|proxyLocationLabel|location=" app tests
```

Expected: evidence originates in `app/proxy_intelligence.py`, persists in `app/database.py`, and is consumed by the Proxy Pool page/export paths.

- [ ] **Step 2: Document the safe boundary**

Record that location aliases affect exact filters, sort order, exports, aggregate labels, and UI presentation, but do not affect generic liveness, duplicate-egress canonicalization, EarnApp qualification, provider-scoped leases, or legacy leases.

- [ ] **Step 3: Record the future recommendation without executing it**

Recommend canonical display at the intelligence/read-model boundary, alias-aware filtering, regression tests, and a separately approved bounded backfill. Explicitly prohibit a bulk live rewrite in this task.

- [ ] **Step 4: Verify the impact map covers every boundary**

Run:

```powershell
rg -n "proxy_intelligence.py|database.py|proxy_pool.html|filter|export|lease|bulk" docs/research/proxy-pool-country-label-impact-map.md
```

Expected: source, persistence, display/filter/export consumers, protected lease paths, and the no-mutation boundary are present.

### Task 2: Define The Import Protocol Contract With Failing Tests

**Files:**
- Modify: `tests/test_proxy_routes.py`

**Interfaces:**
- Consumes: wished-for `_parse_proxy_import(text, protocol_mode)`, `_probe_proxy(..., protocol_mode)`, `_probe_proxy_confirmed(..., protocol_mode)`, `run_proxy_pool_recheck(..., protocol_mode)`, and `_schedule_proxy_import_recheck(..., protocol_mode)` interfaces.
- Produces: regression tests for parser override behavior, invalid API values, forced probing, synchronous import checks, and background import checks.

- [ ] **Step 1: Add parser contract tests**

Add tests equivalent to:

```python
def test_proxy_import_parser_applies_operator_protocol_mode():
    assert proxy_routes._parse_proxy_import("proxy.example:1000", protocol_mode="http")[0]["protocol"] == "http"
    assert (
        proxy_routes._parse_proxy_import("http://proxy.example:1000", protocol_mode="socks5")[0]["protocol"] == "socks5"
    )


def test_proxy_import_parser_auto_preserves_explicit_scheme_and_legacy_default():
    rows = proxy_routes._parse_proxy_import("http://one.example:1000\ntwo.example:2000", protocol_mode="auto")
    assert [row["protocol"] for row in rows] == ["http", "socks5"]
```

- [ ] **Step 2: Add API validation and propagation tests**

Add tests proving `protocol_mode="ftp"` returns HTTP 422, a synchronous forced import calls `run_proxy_pool_recheck(..., protocol_mode="http")`, and a large forced import calls `_schedule_proxy_import_recheck(..., "socks5")`.

- [ ] **Step 3: Add probe-order tests**

Patch `_probe_socks5_proxy`, `_probe_http_proxy`, and `_probe_proxy_exit_ip`. Assert:

```python
await proxy_routes._probe_proxy("proxy.example", 1000, protocol_mode="http")
```

calls only the HTTP handshake, while `protocol_mode="auto"` attempts SOCKS5 before HTTP when SOCKS5 fails.

- [ ] **Step 4: Add background propagation test**

Schedule a background import recheck with `protocol_mode="http"`; await the task and assert `run_proxy_pool_recheck` receives `probe_retries=1` and `protocol_mode="http"` before EarnApp recheck runs.

- [ ] **Step 5: Run focused tests and observe RED**

Run:

```powershell
D:\1. WORK_true\CashPilot\repo\.venv\Scripts\python.exe -m pytest tests/test_proxy_routes.py -k "import_protocol or operator_protocol or scheduled_proxy_import_recheck" -q
```

Expected: new tests fail because the request model and functions do not yet accept `protocol_mode`.

### Task 3: Implement Request-Scoped Protocol Selection

**Files:**
- Modify: `app/routers/proxies.py`
- Test: `tests/test_proxy_routes.py`

**Interfaces:**
- Consumes: `protocol_mode: Literal["auto", "http", "socks5"]` from `ProxyImportIn`.
- Produces: parser records and initial generic checks constrained by the selected mode, with `auto` as the default everywhere else.

- [ ] **Step 1: Add the validated request field**

Import `Literal` and add:

```python
protocol_mode: Literal["auto", "http", "socks5"] = "auto"
```

to `ProxyImportIn`.

- [ ] **Step 2: Apply the mode during parsing**

Change `_parse_proxy_import` to accept `protocol_mode="auto"`. Parse each line as today, then overwrite `parsed["protocol"]` only when the normalized mode is `http` or `socks5`. Preserve explicit schemes and the current unschemed `socks5` default under `auto`.

- [ ] **Step 3: Constrain the probe order**

Add `protocol_mode="auto"` to `_probe_proxy` and `_probe_proxy_confirmed`. Use this order table:

```python
probe_order = ("socks5", "http") if protocol_mode == "auto" else (protocol_mode,)
```

Call only the handshake and exit-IP fetcher corresponding to each entry. Keep the current fail-closed requirement for an authoritative public egress IP.

- [ ] **Step 4: Propagate the mode through only the initial import check**

Add `protocol_mode="auto"` to `run_proxy_pool_recheck` and `_schedule_proxy_import_recheck`. Pass `body.protocol_mode` from the import endpoint to parsing and to its synchronous/background generic recheck. Do not pass it to later scheduler/manual callers, which therefore retain `auto`.

- [ ] **Step 5: Preserve EarnApp sequencing**

Keep generic recheck before EarnApp recheck. EarnApp reads the protocol persisted or detected by the generic pass; do not add a separate EarnApp protocol mode.

- [ ] **Step 6: Run focused tests and observe GREEN**

Run:

```powershell
D:\1. WORK_true\CashPilot\repo\.venv\Scripts\python.exe -m pytest tests/test_proxy_routes.py -k "proxy_pool_import or proxy_import_parser or proxy_probe or scheduled_proxy_import_recheck" -q
```

Expected: all selected tests pass.

### Task 4: Add The Accessible Import Selector

**Files:**
- Modify: `tests/test_frontend_wiring.py`
- Modify: `app/templates/proxy_pool.html`

**Interfaces:**
- Consumes: `ProxyImportIn.protocol_mode`.
- Produces: a labeled `pool-import-protocol` selector with `auto`, `http`, and `socks5` values and a JSON payload containing `protocol_mode`.

- [ ] **Step 1: Write the failing frontend test**

Assert the template contains:

```html
<label class="form-label" for="pool-import-protocol">Protocol</label>
<select class="form-select" id="pool-import-protocol">
```

and option values `auto`, `http`, `socks5`, helper text explaining that Auto detects the protocol, plus:

```javascript
protocol_mode: document.getElementById('pool-import-protocol').value
```

- [ ] **Step 2: Run the frontend test and observe RED**

Run:

```powershell
D:\1. WORK_true\CashPilot\repo\.venv\Scripts\python.exe -m pytest tests/test_frontend_wiring.py -k "proxy_pool_import_protocol" -q
```

Expected: failure because the selector and payload field are absent.

- [ ] **Step 3: Implement the minimal control**

Insert a semantic field between Provider and Proxy file:

```html
<div>
  <label class="form-label" for="pool-import-protocol">Protocol</label>
  <select class="form-select pool-action" id="pool-import-protocol">
    <option value="auto" selected>Auto</option>
    <option value="http">HTTP</option>
    <option value="socks5">SOCKS5</option>
  </select>
  <small class="form-help">Auto detects SOCKS5 or HTTP during the first check.</small>
</div>
```

Update `.pool-import-grid` for five controls while retaining the one-column `max-width:640px` layout. Send the selected value in the import JSON body. Do not auto-submit or trigger a live check merely by changing the selector.

- [ ] **Step 4: Run frontend tests and observe GREEN**

Run:

```powershell
D:\1. WORK_true\CashPilot\repo\.venv\Scripts\python.exe -m pytest tests/test_frontend_wiring.py -k "proxy_pool" -q
```

Expected: all Proxy Pool wiring tests pass.

### Task 5: Verify The Complete Change Locally

**Files:**
- Verify: `app/routers/proxies.py`
- Verify: `app/templates/proxy_pool.html`
- Verify: `tests/test_proxy_routes.py`
- Verify: `tests/test_frontend_wiring.py`
- Verify: `docs/research/proxy-pool-country-label-impact-map.md`

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: fresh local evidence that the change is isolated and releasable.

- [ ] **Step 1: Run focused behavior gates**

Run:

```powershell
D:\1. WORK_true\CashPilot\repo\.venv\Scripts\python.exe -m pytest tests/test_proxy_routes.py tests/test_frontend_wiring.py -k "proxy" -q
```

Expected: zero failures.

- [ ] **Step 2: Run complete repository gates**

Run:

```powershell
D:\1. WORK_true\CashPilot\repo\.venv\Scripts\python.exe -m pytest -q
D:\1. WORK_true\CashPilot\repo\.venv\Scripts\python.exe -m ruff check .
D:\1. WORK_true\CashPilot\repo\.venv\Scripts\python.exe -m ruff format --check .
D:\1. WORK_true\CashPilot\repo\.venv\Scripts\python.exe -m compileall -q app tests
D:\1. WORK_true\CashPilot\repo\.venv\Scripts\python.exe -m mkdocs build --strict
git diff --check
```

Expected: zero test/lint/format/docs failures, successful compilation, and no whitespace errors.

- [ ] **Step 3: Verify protected paths did not change**

Run:

```powershell
git diff --name-only origin/main...HEAD
```

Expected: only the proxy router, Proxy Pool template/tests, plan, and country-label impact map appear; no provider, worker, catalog, collector, wallet, lease SQL, migration, or deployment-runtime file appears.

- [ ] **Step 4: Verify desktop and mobile UI locally**

First run the required helper discovery:

```powershell
D:\1. WORK_true\CashPilot\repo\.venv\Scripts\python.exe C:\Users\KALINH\.codex\skills\webapp-testing\scripts\with_server.py --help
```

Then use the local app test harness with Playwright at `1440px` and `375px`. Confirm the selector has a discoverable label, defaults to Auto, contains all three options, has a minimum 44px target, the import grid stays within the viewport, and changing it does not submit a request.

### Task 6: Ship UI-Only And Audit Read-Only

**Files:**
- Release: UI image paths only.
- Document after live verification only if evidence changes: `docs/ACTIVE_CONTEXT.md` and a Proxy Pool closeout note.

**Interfaces:**
- Consumes: a verified feature branch and merged PR.
- Produces: merged change, release artifacts, a UI-only live deployment, read-only live DOM/API proof, and a final full Proxy Pool audit report.

- [ ] **Step 1: Commit, push, and open the PR**

Commit only scoped files, push `feat/proxy-import-protocol`, and open a PR stating explicitly that no live proxy action, provider change, worker change, migration, or lease change is included.

- [ ] **Step 2: Wait for required CI and merge**

Require Tests, Lint, CodeQL, Documentation, Catalog Check, and release-relevant checks. Treat the known Codecov `file` input warning as pre-existing unless it becomes a required failing check.

- [ ] **Step 3: Let release publish its normal artifacts, then deploy only `cashpilot-ui`**

The release workflow may publish both UI and worker images. Resolve the new UI tag and exact registry digest, but do not pull, recreate, restart, or otherwise alter `cashpilot-worker`.

Resolve the new UI tag and exact registry digest. Recreate only `cashpilot-ui` using the existing UI environment, network, mounts, ports, labels, and restart policy. Verify `cashpilot-worker` container ID, image, start time, restart count, and health remain unchanged.

- [ ] **Step 4: Run read-only live verification**

Authenticate without printing secrets. Verify the live Proxy Pool page contains `pool-import-protocol`, defaults to `auto`, lists `HTTP` and `SOCKS5`, and remains responsive at desktop/mobile widths. Do not click Import, Recheck, EarnApp check, Delete, lease, release, scheduler save, or export raw.

- [ ] **Step 5: Run the final full Proxy Pool audit sweep**

Page read-only through the current inventory and report counts, metadata/label quality, duplicate state, EarnApp evidence freshness, active leases, pagination/response bounds, and UI/UX findings. Compare with the previous baseline without altering rows.

- [ ] **Step 6: Propose the next bounded task**

Recommend the next task based on audit evidence. Keep country-label canonicalization, metadata refresh, EarnApp re-probe, and EarnApp provider implementation as separately approved work.
