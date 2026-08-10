# Provider End-To-End Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make CashPilot install, run, recover, and track supported providers automatically from server-managed credentials/assets through worker runtime.

**Architecture:** CashPilot server is the source of truth for catalog metadata, credentials, assets, proxy egress policy, MYST wallet inventory, and earnings state. Workers only receive scoped runtime material by API/lease, install provider containers with `restart: always`, report runtime evidence, and never require manual SSH/copy for normal provider operation.

**Tech Stack:** Python/FastAPI, SQLite/aiosqlite, Docker SDK, Docker Compose YAML, sing-box egress, CashPilot worker API, browser-smoke via Chrome/Codex tools, pytest.

## Global Constraints

- No provider client deploy test on VPS server.
- Provider client deploy tests run only on `vps-test-sing` from `D:\1. WORK_true\CashPilot\vps\vps-test-sing.txt`.
- Chrome profile is audit/discovery only, not a worker deploy dependency.
- No real provider secret, wallet, cookie, seed, or API key is committed.
- Provider without confirmed current API stays `manual` or `needs_user_info`.
- No new earnings table; per-node earnings use `earnings.source = "node:<provider>:<node_id>"`.
- `Proxy provider` and `Proxy pool` are proxy inventory only, not earning providers.
- MYST wallet inventory is a separate module, not provider catalog.
- HTTP proxy does not satisfy UDP; SOCKS5 UDP only when `udp_ok=true`.
- Direct mode providers bypass fake proxy even when worker default egress is proxy.
- Prefer existing repo patterns, shortest working diff, TDD for behavior changes.

---

## File Structure

- `services/_schema.yml`: credential sections, egress policy schema, provider metadata contract.
- `services/bandwidth/*.yml`, `services/depin/*.yml`: provider source-of-truth.
- `app/catalog.py`: catalog validation and egress/credential metadata loading.
- `app/collectors/__init__.py`: YAML-first collector/deploy/dashboard credential metadata.
- `app/main.py`: API routes still hosted in the legacy main surface.
- `app/routers/myst_wallets.py`: owner-only MYST wallet admin API.
- `app/myst_wallets.py`: wallet normalization, fingerprinting, lease helpers.
- `app/database.py`: encrypted config, MYST wallet inventory, lease state, deployment records.
- `app/worker_api.py`: worker runtime deploy/asset/egress endpoints.
- `app/orchestrator.py`: local Docker deploy with `restart_policy={"Name": "always"}`.
- `app/compose_generator.py`: exported compose with `restart: always`.
- `app/proxy_egress.py`, `app/singbox_config.py`: sing-box policy generation.
- `app/static/js/app.js`, `app/templates/*.html`: Settings, MYST Wallet, Fleet, Dashboard UI.
- `docs/research/provider-refresh-audit-2026-08.md`: audit matrix and current decisions.
- `docs/guides/*.md`, `README.md`, `docs/index.md`: generated/operator docs.
- `tests/test_*`: TDD/contract coverage per task.

## Task 1: Core Checkpoint

**Files:**
- Modify: current working tree
- Test: `tests/test_catalog_loader.py`, `tests/test_compose.py`, `tests/test_main_routes.py`, `tests/test_worker_resources.py`, `tests/test_myst_wallets_module.py`, `tests/test_frontend_wiring.py`

**Interfaces:**
- Produces: clean Git checkpoint for core credential/runtime/MYST stub work.

- [ ] Run targeted tests:

```powershell
pytest tests/test_catalog_loader.py tests/test_compose.py tests/test_main_routes.py tests/test_worker_resources.py tests/test_myst_wallets_module.py tests/test_frontend_wiring.py -q
```

- [ ] Check for secrets:

```powershell
rg -n "api[_-]?key|password|cookie|seed|wallet|private|mnemonic|token" app services docs tests README.md
```

- [ ] Commit/push checkpoint:

```powershell
git add README.md app docs services tests
git commit -m "feat: add provider normalization core"
git push
```

## Task 2: Source-Of-Truth Cleanup

**Files:**
- Modify: `services/**/*.yml`
- Modify: `docs/research/provider-refresh-audit-2026-08.md`
- Modify: `README.md`, `docs/index.md`, `docs/guides/*.md`
- Test: `tests/test_catalog.py`, `tests/test_catalog_loader.py`, `tests/test_readme_generation.py`

**Interfaces:**
- Produces: catalog with exactly 21 intended providers and no stale deleted-provider claims.

- [ ] Add/adjust tests that fail on stale provider refs in catalog-facing docs:

```python
def test_deleted_providers_not_in_catalog_docs():
    deleted = {"honeygain", "passiveapp", "speedshare", "peer2profit"}
    text = Path("docs/research/provider-refresh-audit-2026-08.md").read_text(encoding="utf-8").lower()
    assert not any(f"| {slug} |" in text for slug in deleted)
```

- [ ] Update audit matrix/counts to 21 providers, 16 bandwidth, 5 DePIN, 15 Docker deployable, 15 collectors.
- [ ] Run docs generation if the repo has a generator; otherwise update generated docs only when tests demand it.
- [ ] Verify:

```powershell
pytest tests/test_catalog.py tests/test_catalog_loader.py tests/test_readme_generation.py -q
```

## Task 3: Credential/Asset Architecture

**Files:**
- Modify: `app/catalog.py`
- Modify: `app/collectors/__init__.py`
- Modify: `app/main.py`
- Modify: `app/database.py`
- Modify: `app/static/js/app.js`
- Test: `tests/test_catalog_loader.py`, `tests/test_main_routes.py`, `tests/test_frontend_wiring.py`

**Interfaces:**
- Consumes: `deploy.credentials[]`, `collector.credentials[]`, `dashboard.credentials[]`.
- Produces: settings metadata and save/clear behavior for all three groups without creating fake deployments.

- [ ] Add failing test: Settings metadata returns all 3 groups and secret status.
- [ ] Add failing test: saving deploy/dashboard-only credentials does not create `deployments.status = "external"`.
- [ ] Add failing test: credential health includes expiry for deploy/dashboard credentials.
- [ ] Implement only metadata/config paths needed to pass.
- [ ] Verify:

```powershell
pytest tests/test_catalog_loader.py tests/test_main_routes.py tests/test_frontend_wiring.py -q
```

## Task 4: Worker Runtime Asset Lease

**Files:**
- Modify: `app/worker_api.py`
- Modify: `app/main.py`
- Modify: `app/database.py`
- Create/Modify: `app/runtime_assets.py`
- Test: `tests/test_workers.py`, `tests/test_worker_api_coverage.py`

**Interfaces:**
- Produces: server-managed runtime asset request/response API.
- Worker never reads local provider secrets copied by SSH.

- [ ] Add failing test for worker requesting a provider asset by `provider`, `asset_kind`, `worker_id`.
- [ ] Add failing test for unauthorized worker request returning 401.
- [ ] Add failing test for no raw secret in list/status responses.
- [ ] Implement encrypted asset inventory with minimal kinds: `seed_bundle`, `cookie_bundle`, `dashboard_token`, `wallet_lease_ref`.
- [ ] Verify:

```powershell
pytest tests/test_workers.py tests/test_worker_api_coverage.py -q
```

## Task 5: Proxy Egress Contract

**Files:**
- Modify: `app/proxy_egress.py`
- Modify: `app/singbox_config.py`
- Modify: `app/worker_api.py`
- Modify: `services/**/*.yml`
- Test: `tests/test_proxy_egress.py`, `tests/test_workers.py`

**Interfaces:**
- Consumes: service `egress.mode` and `egress.udp`.
- Produces: direct/proxy/auto sing-box policy that respects UDP capability.

- [ ] Add failing test: HTTP proxy never satisfies UDP provider.
- [ ] Add failing test: SOCKS5 proxy satisfies UDP only when `udp_ok=true`.
- [ ] Add failing test: direct provider bypasses fake proxy.
- [ ] Add failing test: auto chooses direct for UDP-heavy when proxy cannot UDP.
- [ ] Implement minimal policy selection.
- [ ] Verify:

```powershell
pytest tests/test_proxy_egress.py tests/test_workers.py -q
```

## Task 6: MYST Wallet End-To-End

**Files:**
- Modify: `app/myst_wallets.py`
- Modify: `app/routers/myst_wallets.py`
- Modify: `app/database.py`
- Modify: `app/worker_api.py`
- Modify: `app/templates/myst_wallet.html`
- Modify: `app/static/js/app.js`
- Reference only: `D:\1. WORK_true\CashPilot\secret\external-repos\proxy-manager-final`
- Test: `tests/test_myst_wallets_module.py`, `tests/test_workers.py`, `tests/test_worker_api_coverage.py`

**Interfaces:**
- Produces: wallet import/list/filter/export/release/quarantine/funding and worker lease/ack/heartbeat/release.

- [ ] Add failing test: admin list never returns `raw_wallet`.
- [ ] Add failing test: explicit export returns raw wallet only to owner.
- [ ] Add failing test: funded wallet lease changes state `AVAILABLE` to `LEASED`.
- [ ] Add failing test: heartbeat keeps lease alive with redacted evidence.
- [ ] Add failing test: payment-required evidence marks wallet `UNFUNDED`.
- [ ] Implement contract from `proxy-manager-final` in CashPilot style.
- [ ] Verify:

```powershell
pytest tests/test_myst_wallets_module.py tests/test_workers.py tests/test_worker_api_coverage.py -q
```

## Task 7: Provider Automation

**Files:**
- Modify: `services/bandwidth/spide.yml`
- Modify: `services/depin/grass.yml`
- Modify: `services/depin/uprock.yml`
- Modify: `services/depin/wipter.yml`
- Modify: `services/bandwidth/earnapp.yml`
- Modify: `services/bandwidth/proxies-sx.yml`
- Modify/Create: provider runtime helpers under existing worker/provider pattern
- Test: provider-specific tests added beside existing worker/catalog tests

**Interfaces:**
- Produces: provider-specific runtime contracts.

- [ ] `spide`: add two-phase CLI/device-key/register contract and tests.
- [ ] `grass`: add seed-bundle contract; do not lock multi-node defaults until live test.
- [ ] `uprock`: add seed/profile bundle contract and log health markers.
- [ ] `wipter`: add email/password runtime, login-ready markers, restart-once behavior.
- [ ] `earnapp`: keep official VM/Docker/hosting warning; collector stays separate.
- [ ] `proxies-sx`: preserve SDK flow, unique `AGENT_NAME`, per-node earnings notes.
- [ ] Verify:

```powershell
pytest tests/test_catalog_loader.py tests/test_worker_api_coverage.py tests/test_collector_contracts.py -q
```

## Task 8: Grass Live Multi-Node Test

**Files:**
- Write outside repo: `D:\1. WORK_true\CashPilot\secret\providers\grass\dashboard-notes.md`
- Write outside repo: `D:\1. WORK_true\CashPilot\secret\providers\grass\api-samples\*.json`

**Interfaces:**
- Consumes: `vps-test-sing` login file.
- Produces: verified Grass multi-node rule.

- [ ] Read `D:\1. WORK_true\CashPilot\vps\vps-test-sing.txt`.
- [ ] Deploy two Grass test nodes on `vps-test-sing` with same seed and blank/reset `device_id/browser_id`.
- [ ] Wait several minutes.
- [ ] Verify dashboard/runtime output.
- [ ] Save redacted result under `D:\1. WORK_true\CashPilot\secret\providers\grass\`.
- [ ] Update `services/depin/grass.yml` and docs according to observed truth.

## Task 9: Collector/Earnings Normalization

**Files:**
- Modify: `app/collectors/*`
- Modify: `app/main.py`
- Modify: `app/database.py`
- Test: `tests/test_collectors.py`, `tests/test_collector_contracts.py`, `tests/test_main_routes.py`

**Interfaces:**
- Produces: account total plus per-node rows without double-counting.

- [ ] Add failing test: account total and node rows do not double-count.
- [ ] Add failing test: per-node rows use `source="node:<provider>:<node_id>"`.
- [ ] Add failing test: manual/needs_user_info providers do not advertise API collector.
- [ ] Implement minimal fixes.
- [ ] Verify:

```powershell
pytest tests/test_collectors.py tests/test_collector_contracts.py tests/test_main_routes.py -q
```

## Task 10: Final Deploy And Smoke

**Files:**
- Modify: deployment scripts/docs only if required by actual deploy.
- Test: browser smoke and VPS container health.

**Interfaces:**
- Produces: deployed end-to-end CashPilot.

- [ ] Run targeted suite:

```powershell
pytest tests/test_catalog.py tests/test_catalog_loader.py tests/test_collectors.py tests/test_collector_contracts.py tests/test_main_routes.py tests/test_readme_generation.py tests/test_proxy_egress.py tests/test_workers.py tests/test_worker_api_coverage.py tests/test_frontend_wiring.py tests/test_myst_wallets_module.py -q
```

- [ ] Run full suite if practical:

```powershell
pytest -q
```

- [ ] Commit/push final:

```powershell
git add README.md app docs services tests
git commit -m "feat: normalize providers end to end"
git push
```

- [ ] Deploy server/UI.
- [ ] Deploy/update worker on `vps-test-sing`.
- [ ] Smoke pages: Service Catalog, Setup Wizard, Settings, Credential health, Proxy provider, Proxy pool, Fleet, Dashboard, MYST Wallet.
- [ ] Verify containers healthy.

## Self-Review

- Spec coverage: checkpoint, source-of-truth, credential model, worker runtime, proxy egress, MYST Wallet, provider automation, Grass live test, collectors, tests, deploy are covered.
- Placeholder scan: no implementation step relies on hidden values or guessed APIs; provider secrets stay outside repo.
- Type consistency: credential groups remain `deploy_credentials`, `fields`, `dashboard_credentials`; earnings source remains `node:<provider>:<node_id>`.
