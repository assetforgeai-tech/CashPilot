# Consolidation Review Slices — 2026-09-21

Each slice is materialized from `origin/main` plus only the listed migration
paths. Classification is in `consolidation-file-classification-2026-09-21.csv`.

## 1. DB schema, authority, CAS, leases — live risk: critical

Files: `app/database.py`.
Dependencies: SQLite transactions, provider/account/node schemas, proxy leases.
Baseline tests: `tests/test_provider_instances.py`, `tests/test_proxy_routes.py`,
`tests/test_earnapp_account_pool.py`, `tests/test_earnapp_account_routes.py`.

## 2. EarnApp account/token/link/lifecycle/recovery — live risk: critical

Files: `app/earnapp_canary.py`, `app/earnapp_collection.py`,
`app/earnapp_fault_injection.py`, `app/earnapp_lifecycle.py`,
`app/earnapp_runtime.py`, `app/earnapp_staged_recovery.py`,
`services/bandwidth/earnapp.yml`, and all slice-2 tests in the CSV.
Dependencies: slice 1 authority/CAS, worker runtime, collector routes.
Baseline tests: all `tests/test_earnapp_*` paths classified into slice 2.

## 3. Proxy transport, renderer, DNS/firewall/watchdog — live risk: critical

Files: `app/provider_network_audit.py`, `app/proxy_health.py`,
`app/proxy_runtime.py`, `app/singbox_config.py`, and slice-3 tests.
Dependencies: worker Docker/network privileges, proxy metadata, provider catalog.
Baseline tests: `test_provider_network_*`, `test_proxy_egress.py`,
`test_proxy_health.py`, `test_proxy_runtime.py`, `test_proxy_sidecar_runtime.py`.

## 4. Provider topology and allocator policy — live risk: high

Files: `app/provider_modes.py`, `app/provider_topology.py`, and slice-4 tests.
Dependencies: provider runtime truth matrix and proxy capacity.
Baseline tests: `test_auto_deploy_policy.py`, `test_nkn_auto_deploy.py`,
`test_provider_modes.py`, `test_provider_topology.py`.

## 5. Provider catalog/runtime commands — live risk: critical

Files: `app/orchestrator.py`, `app/provider_runtime.py`, `entrypoint.sh`,
`services/bandwidth/proxies-sx.yml`, and slice-5 tests.
Dependencies: Docker SDK/CLI, catalog service definitions, slices 3–4.
Baseline tests: `test_catalog.py`, `test_proxies_sx_topology.py`.

## 6. Collectors, payments, account pools — live risk: high

Files: `app/collectors/proxies_sx.py`, `tests/test_proxies_sx_collector.py`.
Dependencies: provider HTTP API, stored credentials, snapshot persistence.
Baseline tests: `test_proxies_sx_collector.py` plus canonical collector tests.

## 7. API/UI wiring — live risk: critical

Files: `app/main.py`, `app/routers/proxies.py`, `app/static/js/app.js`, and
slice-7 tests.
Dependencies: auth, all control-plane slices, database and worker APIs.
Baseline tests: `test_frontend_wiring.py`, `test_proxy_routes.py`, canonical API tests.

## 8. Worker authentication, release, Azure bootstrap — live risk: critical

Files: `app/worker_api.py`, `azure_create/worker-startup.sh`, `uv.lock`, and
slice-8 tests.
Dependencies: fleet keys, Docker host, startup environment, package resolution.
Baseline tests: `test_azure_worker_startup.py`, `test_nkn_contract_audit.py`,
canonical worker authentication tests.

## 9. Tests and evidence correctness/tools — live risk: medium

Files: `app/proxy_probe_profiles/earnfm.py`,
`tools/live_proxy_network_audit.py`, `tools/preload_current_earnapp_assets.py`,
and slice-9 tests.
Dependencies: provider probes, sanitized evidence formats, runtime APIs.
Baseline tests: `test_earnfm_proxy_probe.py`, `test_provider_active_probe.py`,
`test_provider_instances.py`, `test_provider_lifecycle_policy.py`.

## Gate

All 28 `REVIEW_REQUIRED` paths and 32 `KEEP_TEST` candidates have an owning
slice. Archive/document classifications require no code review and remain frozen.
