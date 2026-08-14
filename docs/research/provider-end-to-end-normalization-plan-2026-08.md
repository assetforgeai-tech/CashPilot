# Provider End-To-End Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize all 18 active CashPilot providers so server Settings, Setup Wizard, Service Catalog, Dashboard, Payouts, Proxy Provider, Proxy Pool, MYST Wallet, and Fleet all agree with the worker runtime and can deploy/recover providers automatically.

**Architecture:** CashPilot server is the only source of truth for provider catalog, credentials, runtime assets, proxy leases, MYST wallet leases, auto-deploy policy, payout metadata, and earnings collection. Workers enroll, heartbeat, receive server commands, apply a single worker-level proxy egress via sing-box, deploy providers sequentially, and report `provider_states`. Proxy Pool and MYST Wallet do not run their own heartbeat loops; they reconcile from CashPilot worker heartbeat plus provider state evidence.

**Tech Stack:** Python/FastAPI, SQLite/aiosqlite, Docker SDK, Docker Compose, sing-box, pytest, Chrome profile 40 audit, browser smoke checks, repo docs generators.

## Execution Ledger

**RESUME_FROM:** Task 17 / Step 1

**CURRENT_STATUS:** [IN_PROGRESS]

**LAST_SAFE_COMMIT:** `42c02df`

**LAST_DEPLOYED_VPS:** `42c02df`

**CURRENT_BRANCH:** `provider-standard-40834f6`

**DO_NOT_TOUCH:** VPS server DB, Docker volumes, committed history, local secret files outside explicit secret audit output.

**Status Labels:**
- `[TODO]`: not started.
- `[IN_PROGRESS]`: currently being edited/tested.
- `[DONE]`: implemented, verified, committed or ready to commit.
- `[BLOCKED]`: cannot progress without external input/access/state.
- `[CHANGED]`: plan changed after work began; decision log must explain why.
- `[DROPPED]`: deliberately removed from scope; decision log must explain why.

**Execution Rules:**
- Before starting a task, update `RESUME_FROM` and change that task to `[IN_PROGRESS]`.
- Before each commit, update completed steps, evidence, and decision log.
- After each commit, write the commit hash into the task checkpoint and `LAST_SAFE_COMMIT`.
- After each VPS deploy, write the deployed commit into `LAST_DEPLOYED_VPS`.
- If Codex crashes or context compacts, resume from `RESUME_FROM`, then verify `LAST_SAFE_COMMIT`, GitHub commit, and VPS commit before touching code.
- If actual code contradicts this plan, mark the task `[CHANGED]` and add a decision log entry before implementing.
- If a credential/token/raw secret is discovered, write it only to `D:\1. WORK_true\CashPilot\secret\provider-credential-gap-audit.md` or directly into server Settings.
- Server Settings writes are allowed only through authenticated CashPilot app API/UI, never by direct DB editing.
- Before overwriting any existing credential, record old `is_set`, age, health status, and verify result in the local secret audit file.

### Decision Log

| Time | Status | Decision | Reason | Impact | Commit |
| --- | --- | --- | --- | --- | --- |
| 2026-08-13 | [CHANGED] | Add execution ledger, resume marker, deploy checkpoint, and provider progress matrix. | Prevent lost state after Codex crash/compaction and prevent deploy from wrong commit. | Every task must update status/evidence before commit/deploy. | pending |
| 2026-08-13 | [CHANGED] | Add guard/clarity fixes without changing approved architecture. | Plan audit found ambiguous Chrome, MYST ACK, provider unknowns, proxybase naming, runtime tests, commit checkpoint, settings writes, auto-deploy locking, credential overwrite audit. | Execution must resolve ambiguity before coding. | pending |
| 2026-08-13 | [CHANGED] | Replace stale worker test filenames in plan with existing repo tests. | Repo has `test_worker_keys.py` and `test_worker_myst_sync.py`, not `test_workers.py` or `test_worker_api_coverage.py`. | Verification commands now match actual suite without changing architecture. | pending |
| 2026-08-13 | [DONE] | Settings deploy credentials now mark deployed providers `needs_redeploy`; collector/dashboard credentials do not. | Runtime material changes require recreating provider containers, but collector/session-only changes should only affect collection/verification. | Settings contract matches worker deploy source-of-truth without adding a scheduler. | pending |
| 2026-08-13 | [DONE] | Credential health now has regression coverage for age/status without leaking values. | The settings panel must show freshness and expiry truth without printing secrets. | Health UI can warn before provider collection dies. | pending |
| 2026-08-13 | [DONE] | Worker bootstrap contract verified against existing fleet UI and worker key tests. | Current code already uses public IP/timestamp copy snippet, public worker URL, stable client_id, worker key re-enrollment, and MYST provider state on worker heartbeat. | No extra runtime logic added for Task 5. | pending |
| 2026-08-13 | [DONE] | Auto-deploy policy now has server-side toggle/delay and sequential worker batch behavior. | Stable workers can be auto-sequenced from heartbeat after 3 healthy beats, with per-worker locking and deployable-only filtering. | Auto deploy is opt-in, per-worker, and continues after per-provider failure. | pending |
| 2026-08-15 | [CHANGED] | Adnade, Dawn, and Titan are removed from the active plan scope. | User explicitly dropped the three Chrome-extension providers; active catalog now has 18 providers. | Remaining work targets active providers only and docs/tests must use 18-provider source-of-truth. | `42c02df` |
| 2026-08-15 | [IN_PROGRESS] | Add provider instance mode UI/API wiring as the first core runtime checkpoint. | Providers need direct/proxy/both instances on the same worker without container collisions. | Setup Wizard and Service Detail now send deploy `mode`; VPS is deployed at `42c02df`. | `42c02df` |

### Open Drift

| Status | Area | Drift | Next Action |
| --- | --- | --- | --- |
| [DONE] | VPS deploy | `LAST_DEPLOYED_VPS` verified at `42c02df`. | Continue provider runtime normalization from current deployed commit. |
| [TODO] | Chrome audit | Chrome profile 40 tab inventory not captured in this plan file yet. | Capture provider tab list during Task 1. |
| [TODO] | Credentials | Some server Settings credentials may be missing/expired. | Audit and write gaps to local secret file. |
| [IN_PROGRESS] | Provider runtime | Active catalog has 18 providers, but runtime contracts still need full normalization against manual setup scripts. | Execute Task 17. |

### Deploy Checkpoint

| Surface | Expected | Actual | Status | Evidence |
| --- | --- | --- | --- | --- |
| Local branch | `provider-standard-40834f6` | `provider-standard-40834f6` | [DONE] | `git rev-parse --abbrev-ref HEAD` |
| Local commit | `52aadfe` or newer | `52aadfe` before this plan edit | [CHANGED] | Plan edit pending commit |
| GitHub commit | Match local after push | unknown | [TODO] | Check before deploy |
| VPS server commit | Match GitHub after deploy | unknown | [TODO] | Check before deploy |

### Provider Progress Matrix

| Provider | Status | Deploy Runtime | Earnings Collector | Dashboard / Session | Payout | Proxy / Direct | Runtime Test | UI Ready | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| grass | [TODO] | 7 store.json keys | existing/verify | dashboard audit | needs_user_info | direct | prior manual success, needs codified test | partial | Keys: `wynd:status`, `wynd:user_id`, `tokenExpiry`, `autoUpdate`, `wynd:authenticated`, `refreshToken`, `accessToken`. |
| uprock | [TODO] | `credentials.json` + `main.db` | limited/no API unless confirmed | dashboard audit | needs_user_info | direct | prior manual success | partial | Official runtime only. |
| wipter | [TODO] | email/password | scrape/manual unless API confirmed | dashboard audit | needs_user_info | provider tunnel namespace | partial | partial | Needs login marker verification. |
| bitping | [TODO] | catalog deploy credential audit | existing/verify | dashboard audit | payout audit | direct | pending | pending | Direct provider. |
| earnapp | [TODO] | deploy credential separated | OAuth refresh/cookie | dashboard audit | payout audit | proxy or direct by policy | pending | pending | Keep official Docker/hosting warning. |
| earnfm | [TODO] | deploy credential audit | existing/verify | dashboard audit | payout audit | direct | pending | pending | Direct provider. |
| iproyal | [TODO] | deploy credential audit | existing/verify | dashboard audit | payout audit | proxy policy audit | pending | pending | Audit required. |
| mysterium | [TODO] | MYST wallet lease + password | provider state only unless API confirmed | MYST dashboard password/MMN | MYST-specific | direct | partial | partial | Wallet handled by MYST Wallet module. |
| packetstream | [TODO] | deploy credential audit | existing/verify | dashboard audit | payout audit | proxy policy audit | pending | pending | Audit required. |
| proxies-sx | [TODO] | unique `AGENT_NAME` | per-node collector | dashboard audit | payout audit | proxy policy audit | pending | pending | Connected is not necessarily earning. |
| proxybase | [TODO] | node access token | dashboard token | dashboard token | payout audit | direct | pending | partial | `ghcr.io/proxybaseorg/peer-cli:latest <access_token> <device_name>`. |
| proxybase-xyz | [TODO] | wallet phrase/phase | node count/manual | none unless found | payout audit | proxy policy audit | pending | partial | Separate provider from `proxybase`; CLI flow uses `https://proxybase.xyz/install.sh`, install path may change. |
| proxylite | [TODO] | `PROXYLITE_USER_ID` | node count/manual | none unless found | payout audit | direct | pending | partial | `proxylite/proxyservice`. |
| proxyrack | [TODO] | deploy credential audit | existing/verify | dashboard audit | payout audit | direct | pending | pending | Direct provider. |
| repocket | [TODO] | deploy credential audit | existing/verify | dashboard audit | payout audit | direct | pending | pending | Direct provider. |
| spide | [TODO] | CLI device key | needs_user_info | dashboard token/cookie | payout audit | proxy policy audit | pending | pending | Device create API flow; collector requires proven API or scrape shape. |
| traffmonetizer | [TODO] | deploy credential audit | existing/verify | dashboard audit | payout audit | direct | pending | pending | Direct provider. |
| urnetwork | [TODO] | deploy credential audit | existing/verify | Chrome tab audit | payout audit | proxy policy audit | pending | pending | Chrome tab open. |

## Global Constraints

- Normalize all 18 active providers in `services/bandwidth/*.yml` and `services/depin/*.yml`.
- No provider client deploy test on VPS server.
- Provider client deploy tests run on test workers, primarily `vps-test-sing`.
- VPS server is deploy source of truth; provider nodes are created through server-to-worker flow.
- Never deploy providers directly on a worker as the final validation path.
- No real provider secret, wallet, cookie, seed, or API key is committed.
- Local secret audit output may contain raw secrets only under `D:\1. WORK_true\CashPilot\secret\provider-credential-gap-audit.md`.
- `D:\1. WORK_true\CashPilot\secret\provider-credential-gap-audit.md` is plaintext, local-only, and never committed.
- Chrome profile 40 is the credential/API audit source.
- Chrome profile 40 is already open with all provider tabs; Task 1 must connect to Chrome. If the first connector fails, treat that as a connection bug to fix, not as permission to skip Chrome audit.
- Chrome audit may read cookies, localStorage, network-visible tokens, dashboard/session data, and provider page DOM.
- Chrome audit may auto-save valid provider credentials into the VPS server Settings.
- Chrome audit overwrites a credential only after the existing credential is missing, expired, failing, or verified not alive.
- Chrome credential overwrite must record old `is_set`, age, health status, and verify result before writing the replacement.
- Provider without confirmed deploy/API truth stays explicit `needs_user_info` with exact missing fields.
- No new earnings table; per-node earnings use `earnings.source = "node:<provider>:<node_id>"`.
- Collector runs on the server, not the worker.
- `Proxy provider` and `Proxy pool` are proxy inventory/lease modules, not earning providers.
- Proxy lease is exclusive per worker.
- Every worker leases one default proxy for sing-box proxy egress.
- Proxy health check interval is configurable in Settings; default is 5 minutes.
- Proxy auto-rotate toggle is configurable in Settings.
- When a worker proxy dies, server rotates that worker proxy and worker restarts only sing-box.
- Proxy-mode providers stop deploying when no proxy is available; direct providers still deploy.
- Direct providers bypass fake proxy and run through VPS public IP.
- MYST Wallet is separate asset inventory, not provider catalog.
- MYST wallet release/reclaim follows CashPilot worker heartbeat/provider state.
- Worker offline threshold for proxy/MYST reclaim is 5 minutes.
- MYST default dashboard password is stored in Settings and applies to new/redeployed nodes only.
- MYST funding status is derived only from `Registration Status: Registered` or `Registration Status: Unregistered`.
- If MYST registration status cannot be read, keep the previous wallet funding state.
- Auto deploy is off by default.
- Auto deploy never runs on the VPS server/local server worker by default.
- Auto deploy applies to deployable providers only.
- Auto deploy deploys missing providers on old and new workers.
- Auto deploy starts after 3 consecutive healthy worker heartbeats.
- Auto deploy deploys providers sequentially per worker.
- Auto deploy must use a per-worker job lock so two auto-deploy batches cannot run on the same worker at the same time.
- Auto deploy delay is configurable in Settings; default is 10 seconds.
- Auto deploy continues after individual provider failure.
- Multiple workers may auto deploy at the same time.
- Runtime deploy credential change triggers provider redeploy.
- Collector/dashboard/session credential change triggers reverify/recollect, not redeploy.
- Settings has fixed sections: Environment Variables, Credential health, Provider Credentials, Deploy runtime, Earnings collector, Dashboard / session.
- Service Catalog shows separate readiness badges: deploy, collector, dashboard/session.
- Fleet shows worker/provider state and auto-deploy status; no per-worker auto-deploy toggle.
- Prefer existing repo patterns, deletion over addition, TDD for behavior changes.

---

## Milestones

### Milestone 1: Audit Lock
All provider/UI/backend gaps are known, credential gaps are written outside repo, and stale/thrown-away logic is removed from the plan.

### Milestone 2: Core Contracts
Settings, credential health, runtime assets, worker heartbeat/provider_states, proxy lease, MYST wallet lease, and auto-deploy policy have server-side contracts and tests.

### Milestone 3: UI Parity
Dashboard, Setup Wizard, Service Catalog, Payouts, Proxy Provider, Proxy Pool, MYST Wallet, Settings, and Fleet expose exactly what backend supports.

### Milestone 4: Provider Contracts
All 18 active providers have deploy runtime, earnings collector, dashboard/session, payout, proxy mode, and readiness metadata filled or explicitly marked `needs_user_info`.

### Milestone 5: Server-First Live Validation
VPS server is deployed from GitHub, workers enroll via the bootstrap script, and provider nodes are recreated only from server commands.

---

## File Structure

- `services/_schema.yml`: provider metadata schema for credentials, runtime assets, proxy policy, payout, readiness.
- `services/bandwidth/*.yml`, `services/depin/*.yml`: source-of-truth provider contracts.
- `app/catalog.py`: catalog loading, validation, and readiness metadata.
- `app/collectors/__init__.py`: collector metadata and credential field normalization.
- `app/collectors/*.py`: provider earnings/payout collectors.
- `app/database.py`: config, credential metadata, workers, deployments, proxy leases, MYST wallets, provider states.
- `app/main.py`: Settings, Dashboard, Setup Wizard, Fleet, deploy, payout, and collector routes.
- `app/worker_api.py`: worker enroll/heartbeat/provider_states/deploy/runtime asset hooks.
- `app/orchestrator.py`: Docker deploy/remove/redeploy and provider evidence extraction.
- `app/provider_automation.py`, `app/provider_installers.py`: provider-specific runtime helpers.
- `app/proxy_egress.py`, `app/singbox_config.py`, `app/routers/proxies.py`: proxy provider/pool/worker egress.
- `app/myst_wallets.py`, `app/myst_runtime.py`, `app/routers/myst_wallets.py`: MYST wallet inventory/runtime flow.
- `app/payouts.py`, `app/payout_reconcile.py`, `app/payout_registry.py`: payout detection, display, confirmation.
- `app/templates/*.html`, `app/static/js/app.js`: frontend parity.
- `client command setup script.txt`: canonical VPS worker bootstrap.
- `docs/research/provider-refresh-audit-2026-08.md`: provider status matrix.
- `D:\1. WORK_true\CashPilot\secret\provider-credential-gap-audit.md`: local secret/credential gap file, not committed.
- `tests/test_*`: unit, contract, wiring, and regression coverage.

---

## Task 1 [DONE]: Full Audit Inventory

**Files:**
- Modify: `docs/research/provider-refresh-audit-2026-08.md`
- Create/Modify outside repo: `D:\1. WORK_true\CashPilot\secret\provider-credential-gap-audit.md`
- Test: `tests/test_catalog.py`, `tests/test_catalog_loader.py`, `tests/test_provider_source_of_truth_docs.py`

**Interfaces:**

**Checkpoint:** Status [DONE]; Owner Codex; Started 2026-08-13; Evidence `86 passed`, removed unused `ack_myst_wallet`; Commit pending.

- Produces: complete 21-provider matrix with runtime, collector, dashboard/session, payout, proxy, MYST dependency, UI readiness, missing credentials.

- [x] Load all provider YAML files and list the active provider slugs.
- [x] For each provider, record `category`, `deployable`, `container image`, `deploy credentials`, `runtime assets`, `collector credentials`, `dashboard/session credentials`, `payout fields`, `egress mode`, `proxy requirement`, `MYST dependency`, `UI readiness`.
- [x] Search docs/UI/tests for stale provider names and stale counts.
- [x] Connect to Chrome profile 40 and read all provider tab URL/title/page state. If the Chrome connector fails, fix the connection path or use an approved fallback; do not skip Chrome audit.
- [x] Extract provider tokens/cookies/API/session fields from Chrome profile 40 when needed.
- [x] Save missing/raw credential notes only to `D:\1. WORK_true\CashPilot\secret\provider-credential-gap-audit.md`.
- [x] Add tests that fail when docs provider counts disagree with loaded catalog counts.
- [x] Replace every provider matrix `unknown` value with a concrete field, `none`, `not_applicable`, or `needs_user_info`.

**Verification:**

```powershell
pytest tests/test_catalog.py tests/test_catalog_loader.py tests/test_provider_source_of_truth_docs.py -q
```

---

## Task 2 [DONE]: Remove Redundant Logic

**Files:**
- Modify: `app/worker_api.py`
- Modify: `app/myst_wallets.py`
- Modify: `app/routers/myst_wallets.py`
- Modify: `app/database.py`
- Modify: `tests/test_worker_myst_sync.py`
- Modify: `tests/test_myst_wallets_module.py`

**Interfaces:**

**Checkpoint:** Status [TODO]; Owner Codex; Started not yet; Evidence pending; Commit pending.

- Produces: single worker heartbeat plus `provider_states` as runtime truth.

- [x] Remove any separate MYST heartbeat loop or endpoint that duplicates worker heartbeat.
- [x] Remove any MYST ACK endpoint. If code audit proves provider_states cannot carry required evidence, mark this task `[CHANGED]` and add a decision log entry before adding any replacement.
- [x] Keep wallet lease state on server as asset inventory, not runtime truth.
- [x] Make stale wallet/proxy decisions consume worker `last_heartbeat` and `provider_states`.
- [x] Add tests proving MYST wallet logic does not require a separate heartbeat endpoint.

**Verification:**

```powershell
pytest tests/test_worker_myst_sync.py tests/test_myst_wallets_module.py tests/test_worker_keys.py -q
```

---

## Task 3 [DONE]: Settings Contract

**Files:**
- Modify: `app/catalog.py`
- Modify: `app/collectors/__init__.py`
- Modify: `app/main.py`
- Modify: `app/database.py`
- Modify: `app/static/js/app.js`
- Modify: `app/templates/settings.html`
- Test: `tests/test_main_routes.py`, `tests/test_frontend_wiring.py`, `tests/test_deploy_credentials.py`, `tests/test_runtime_assets.py`

**Interfaces:**

**Checkpoint:** Status [DONE]; Owner Codex; Started 2026-08-13; Evidence `98 passed` (`tests/test_settings_contract.py`, `tests/test_frontend_wiring.py`, `tests/test_deploy_credentials.py`, `tests/test_runtime_assets.py`); Commit pending.

- Produces: fixed Settings sections and correct save/clear/reverify/redeploy behavior.

- [x] Add tests for Settings sections: Environment Variables, Credential health, Provider Credentials, Deploy runtime, Earnings collector, Dashboard / session.
- [x] Add tests that deploy credential changes mark provider `needs_redeploy`.
- [x] Add tests that collector/dashboard credential changes trigger verify/recollect only.
- [x] Add tests that file inputs persist as runtime assets without echoing raw values.
- [x] Add tests that stale/incomplete UI status matches backend metadata.
- [x] Implement minimal backend and frontend changes to pass.

**Verification:**

```powershell
pytest tests/test_main_routes.py tests/test_frontend_wiring.py tests/test_deploy_credentials.py tests/test_runtime_assets.py -q
```

---

## Task 4 [DONE]: Credential Health And Chrome Audit Save

**Files:**
- Modify: `app/credential_test.py`
- Modify: `app/main.py`
- Modify: `app/database.py`
- Modify: `app/static/js/app.js`
- Create/Modify outside repo: `D:\1. WORK_true\CashPilot\secret\provider-credential-gap-audit.md`
- Test: `tests/test_main_routes.py`, `tests/test_collectors.py`, `tests/test_collector_contracts.py`

**Interfaces:**

**Checkpoint:** Status [DONE]; Owner Codex; Started 2026-08-13; Evidence `100 passed, 1 skipped` (`tests/test_settings_contract.py`, `tests/test_collectors.py`, `tests/test_collector_contracts.py`); Commit pending.

- Produces: credential verification before overwrite and local gap report.

- [x] Add tests for existing fresh credential not overwritten.
- [x] Add tests for missing/expired/failing credential eligible for overwrite.
- [x] Add tests for unknown expiry reporting `no_known_expiry`.
- [x] Add Chrome audit procedure that writes raw secret only to local secret file or directly into server Settings.
- [x] Add provider-specific credential verification where APIs are known.

**Verification:**

```powershell
pytest tests/test_main_routes.py tests/test_collectors.py tests/test_collector_contracts.py -q
```

---

## Task 5 [DONE]: Worker Bootstrap And Stable Heartbeat

**Files:**
- Modify: `client command setup script.txt`
- Modify: `app/worker_api.py`
- Modify: `app/database.py`
- Modify: `app/templates/fleet.html`
- Modify: `app/static/js/app.js`
- Test: `tests/test_worker_keys.py`, `tests/test_worker_keys.py`, `tests/test_worker_myst_sync.py`

**Interfaces:**

**Checkpoint:** Status [DONE]; Owner Codex; Started 2026-08-13; Evidence `136 passed` (`tests/test_worker_keys.py`, `tests/test_worker_myst_sync.py`, `tests/test_frontend_wiring.py`); external bootstrap script verified at `D:\1. WORK_true\CashPilot\client command setup script.txt`; Commit pending.

- Produces: stable worker identity, worker URL, worker online threshold, server-first deploy path.

- [x] Add tests for worker name `public-ip-timestamp`.
- [x] Add tests for worker URL using public VPS IP, not container-internal IP.
- [x] Add tests for worker stable after 3 consecutive healthy heartbeats.
- [x] Add tests that local/VPS server worker is excluded from auto deploy by default.
- [x] Keep bootstrap script compatible with old and new VPS package state.

**Verification:**

```powershell
pytest tests/test_worker_keys.py tests/test_worker_keys.py tests/test_worker_myst_sync.py -q
```

---

## Task 6 [DONE]: Auto Deploy Policy

**Files:**
- Modify: `app/main.py`
- Modify: `app/database.py`
- Modify: `app/worker_api.py`
- Modify: `app/orchestrator.py`
- Modify: `app/static/js/app.js`
- Modify: `app/templates/settings.html`
- Modify: `app/templates/fleet.html`
- Test: `tests/test_worker_keys.py`, `tests/test_worker_myst_sync.py`, `tests/test_frontend_wiring.py`

**Interfaces:**

**Checkpoint:** Status [DONE]; Owner Codex; Started 2026-08-13; Evidence `84 passed` (`tests/test_auto_deploy_policy.py`, `tests/test_frontend_wiring.py`); Commit pending.

- Produces: global auto-deploy toggle, delay, batch sequence, failure continuation, credential-change redeploy.

- [x] Add tests for auto deploy disabled by default.
- [x] Add tests for deployable providers only.
- [x] Add tests for old workers receiving missing providers when toggle is enabled.
- [x] Add tests for new workers starting auto deploy after 3 healthy heartbeats.
- [x] Add tests for one auto-deploy job lock per worker.
- [x] Add tests for 10-second default provider delay and configurable delay.
- [x] Add tests for provider failure recorded while the batch continues.
- [x] Add tests for deploy credential change triggering redeploy.
- [x] Implement sequential per-worker batch deploy.

**Verification:**

```powershell
pytest tests/test_worker_keys.py tests/test_worker_myst_sync.py tests/test_frontend_wiring.py -q
```

---

## Task 7 [DONE]: Proxy Provider And Proxy Pool Lease

**Files:**
- Modify: `app/routers/proxies.py`
- Modify: `app/database.py`
- Modify: `app/proxy_egress.py`
- Modify: `app/singbox_config.py`
- Modify: `app/worker_api.py`
- Modify: `app/templates/*.html`
- Modify: `app/static/js/app.js`
- Test: `tests/test_proxy_routes.py`, `tests/test_proxy_egress.py`, `tests/test_worker_keys.py`, `tests/test_frontend_wiring.py`

**Interfaces:**

**Checkpoint:** Status [DONE]; Owner Codex; Started 2026-08-13; Evidence `11 passed` (`tests/test_proxy_routes.py`, `tests/test_auto_deploy_policy.py`); Commit pending.

- Produces: one exclusive worker-level proxy lease, health checks, auto-rotate, sing-box restart.

- [x] Add tests for proxy lease exclusive per worker.
- [x] Add tests that each worker receives one default proxy for sing-box.
- [x] Add tests that proxy health check interval defaults to 5 minutes and is configurable.
- [x] Add tests that proxy auto-rotate can be toggled.
- [x] Add tests that failed proxy rotates to a new available proxy for the same worker.
- [x] Add tests that worker restarts only sing-box after proxy rotation.
- [x] Add tests that proxy-mode provider deploy blocks when no proxy is available.
- [x] Add tests that direct providers deploy even when proxy pool is empty.
- [x] Update Proxy Provider UI for inventory/capability health.
- [x] Update Proxy Pool UI for worker lease, proxy state, last check, rotate reason.

**Verification:**

```powershell
pytest tests/test_proxy_routes.py tests/test_proxy_egress.py tests/test_worker_keys.py tests/test_frontend_wiring.py -q
```

---

## Task 8 [DONE]: MYST Wallet Lease And Runtime

**Files:**
- Modify: `app/myst_wallets.py`
- Modify: `app/myst_runtime.py`
- Modify: `app/routers/myst_wallets.py`
- Modify: `app/database.py`
- Modify: `app/worker_api.py`
- Modify: `app/templates/myst_wallet.html`
- Modify: `app/static/js/app.js`
- Test: `tests/test_myst_wallets_module.py`, `tests/test_myst_runtime.py`, `tests/test_worker_myst_sync.py`, `tests/test_worker_keys.py`

**Interfaces:**

**Checkpoint:** Status [DONE]; Owner Codex; Started 2026-08-13; Evidence `38 passed` (`tests/test_myst_runtime.py`, `tests/test_myst_wallets_module.py`, `tests/test_worker_myst_sync.py`); Commit pending.

- Produces: MYST wallet distribution/reclaim through worker heartbeat/provider_states.

- [x] Add tests for wallet fingerprint uniqueness across fleet.
- [x] Add tests for one MYST direct node per worker.
- [x] Add tests for default password stored in Settings and applied to new/redeployed nodes.
- [x] Add tests for `Registered` marking wallet `FUNDED`.
- [x] Add tests for `Unregistered` marking wallet `UNFUNDED`.
- [x] Add tests for unreadable registration status preserving previous funding state.
- [x] Add tests for worker offline over 5 minutes making wallet reusable by another worker.
- [x] Add tests for stale old worker heartbeat blocked by assignment version/provider_states.
- [x] Update MYST Wallet UI with import/list/filter/export/release/quarantine/funding state.
- [x] Keep MYST release/reclaim automatic; no manual release required for normal flow.

**Verification:**

```powershell
pytest tests/test_myst_wallets_module.py tests/test_myst_runtime.py tests/test_worker_myst_sync.py tests/test_worker_keys.py -q
```

---

## Task 9 [DONE]: Provider Catalog Contracts For 21 Providers

**Files:**
- Modify: `services/bandwidth/bitping.yml`
- Modify: `services/bandwidth/earnapp.yml`
- Modify: `services/bandwidth/earnfm.yml`
- Modify: `services/bandwidth/iproyal.yml`
- Modify: `services/bandwidth/mysterium.yml`
- Modify: `services/bandwidth/packetstream.yml`
- Modify: `services/bandwidth/proxies-sx.yml`
- Modify: `services/bandwidth/proxybase.yml`
- Modify: `services/bandwidth/proxybase-xyz.yml`
- Modify: `services/bandwidth/proxylite.yml`
- Modify: `services/bandwidth/proxyrack.yml`
- Modify: `services/bandwidth/repocket.yml`
- Modify: `services/bandwidth/spide.yml`
- Modify: `services/bandwidth/traffmonetizer.yml`
- Modify: `services/bandwidth/urnetwork.yml`
- Modify: `services/depin/grass.yml`
- Modify: `services/depin/uprock.yml`
- Modify: `services/depin/wipter.yml`
- Test: `tests/test_catalog.py`, `tests/test_catalog_loader.py`, `tests/test_provider_automation.py`, `tests/test_provider_installers.py`

**Interfaces:**

**Checkpoint:** Status [DONE]; Owner Codex; Started 2026-08-13; Evidence `208 passed` (`tests/test_catalog.py`, `tests/test_catalog_loader.py`, `tests/test_provider_source_of_truth_docs.py`); Commit pending.

- Produces: every provider has deploy runtime, collector, dashboard/session, payout, egress, and readiness metadata either implemented or explicitly missing.

- [x] Mark every deployable provider with exact deploy runtime fields.
- [x] Mark every collector-capable provider with exact earnings collector fields.
- [x] Mark every dashboard/API-capable provider with exact dashboard/session fields.
- [x] Mark every payout-capable collector provider with withdrawable/minimum/dashboard URL fields.
- [x] Mark every proxy-mode provider as proxy egress.
- [x] Mark direct providers explicitly: Grass, Uprock, EarnFM, Proxybase.org, Proxyrack, Repocket, Traffmonetizer, Proxylite, Bitping, MYST.
- [x] Keep provider names unambiguous: `proxybase` is Docker `ghcr.io/proxybaseorg/peer-cli`; `proxybase-xyz` is CLI `https://proxybase.xyz/install.sh`.
- [x] Keep MYST wallet dependency separate from proxy provider wallet.
- [x] For provider fields not yet known, write exact gap to local secret audit file and set catalog `needs_user_info`.

**Verification:**

```powershell
pytest tests/test_catalog.py tests/test_catalog_loader.py tests/test_provider_automation.py tests/test_provider_installers.py -q
```

---

## Task 10 [DONE]: Provider Runtime Helpers

**Files:**
- Modify: `app/provider_automation.py`
- Modify: `app/provider_installers.py`
- Modify: `app/orchestrator.py`
- Modify: `app/worker_api.py`
- Test: `tests/test_provider_automation.py`, `tests/test_provider_installers.py`, `tests/test_worker_keys.py`, `tests/test_worker_myst_sync.py`, plus one new focused test file when a new helper cannot fit those contracts cleanly.

**Interfaces:**

**Checkpoint:** Status [DONE]; Owner Codex; Started 2026-08-13; Evidence `40 passed` (`tests/test_provider_automation.py`, `tests/test_provider_installers.py`, `tests/test_grass_deploy_automation.py`, `tests/test_optional_runtime.py`); Commit pending.

- Produces: deploy helpers that materialize runtime assets into containers correctly.

- [x] Adnade: download R2 `.fernet`, decrypt profile on worker, run Chrome profile from InternetIncome test branch behavior, preserve Dawn, auto-enable Titan.
- [x] Grass: patch 7 required `store.json` keys and restart Grass.
- [x] Uprock: materialize `credentials.json` and `main.db`, run official image/package flow, verify earning state.
- [x] Wipter: run email/password login flow, detect login-ready markers, restart once.
- [x] Proxybase: run official Docker token/device flow.
- [x] Proxylite: run `proxylite/proxyservice` with `USER_ID`.
- [x] Spide: run Linux CLI, parse device key, register through dashboard/session credential.
- [x] MYST: lease wallet, write local wallet with `0600`, set password/MMN, start node, report registration status.

**Verification:**

```powershell
pytest tests/test_provider_automation.py tests/test_provider_installers.py tests/test_worker_keys.py tests/test_worker_myst_sync.py -q
```

---

## Task 11 [DONE]: Dashboard And Payouts

**Files:**
- Modify: `app/main.py`
- Modify: `app/payouts.py`
- Modify: `app/payout_reconcile.py`
- Modify: `app/payout_registry.py`
- Modify: `app/static/js/app.js`
- Modify: `app/templates/dashboard.html`
- Modify: `app/templates/payouts.html`
- Test: `tests/test_payout_earnings.py`, `tests/test_payout_reconcile.py`, `tests/test_main_routes.py`, `tests/test_frontend_wiring.py`

**Interfaces:**

**Checkpoint:** Status [DONE]; Owner Codex; Started 2026-08-13; Evidence `88 passed` for frontend/proxy route slice plus `18 passed` payout slice; Commit pending.

- Produces: dashboard and payouts that reflect collector truth without guessing.

- [x] Add tests for payout showing `withdrawable`, `minimum`, `eligible`, `dashboard_url`, `last_checked`.
- [x] Add tests for no collector showing `running/no collector`.
- [x] Add tests for per-node earnings source not double-counting account total.
- [x] Add tests for Collect Now per provider.
- [x] Update Dashboard provider cards with runtime/credential/proxy/wallet/collector status.
- [x] Update Payouts page to show only collector-backed payout information.

**Verification:**

```powershell
pytest tests/test_payout_earnings.py tests/test_payout_reconcile.py tests/test_main_routes.py tests/test_frontend_wiring.py -q
```

---

## Task 12 [DONE]: Setup Wizard And Service Catalog

**Files:**
- Modify: `app/main.py`
- Modify: `app/static/js/app.js`
- Modify: `app/templates/setup.html`
- Modify: `app/templates/catalog.html`
- Modify: `app/templates/service_detail.html`
- Test: `tests/test_main_routes.py`, `tests/test_frontend_wiring.py`, `tests/test_catalog.py`

**Interfaces:**

**Checkpoint:** Status [DONE]; Owner Codex; Started 2026-08-13; Evidence `288 passed` for frontend/catalog/catalog-loader slice; Commit pending.

- Produces: multi-provider deploy flow and readiness visibility.

- [x] Add tests for Setup Wizard selecting multiple providers and one or more workers.
- [x] Add tests for Setup Wizard respecting deploy/collector/dashboard fields.
- [x] Add tests for Setup Wizard skipping providers with missing deploy runtime fields.
- [x] Add tests for Service Catalog readiness badges: deploy, collector, dashboard/session.
- [x] Add tests for Service Catalog showing egress/direct/proxy/MYST dependency.
- [x] Implement minimal UI changes for batch deploy and readiness.

**Verification:**

```powershell
pytest tests/test_main_routes.py tests/test_frontend_wiring.py tests/test_catalog.py -q
```

---

## Task 13 [DONE]: Fleet UI And Reconciliation

**Files:**
- Modify: `app/main.py`
- Modify: `app/database.py`
- Modify: `app/templates/fleet.html`
- Modify: `app/static/js/app.js`
- Test: `tests/test_worker_keys.py`, `tests/test_worker_keys.py`, `tests/test_frontend_wiring.py`

**Interfaces:**

**Checkpoint:** Status [DONE]; Owner Codex; Started 2026-08-13; Evidence `115 passed` for fleet/MYST slice; Commit pending.

- Produces: worker/provider_states, auto-deploy progress, proxy lease, MYST lease, runtime evidence in Fleet.

- [x] Add tests for Fleet showing worker public IP, URL, last heartbeat, stable heartbeat state.
- [x] Add tests for Fleet showing provider_states by worker.
- [x] Add tests for Fleet showing auto-deploy batch status.
- [x] Add tests for Fleet showing proxy lease and MYST wallet lease redacted.
- [x] Add tests for automatic reconciliation from worker heartbeat.
- [x] Implement minimal frontend/backend additions.

**Verification:**

```powershell
pytest tests/test_worker_keys.py tests/test_worker_keys.py tests/test_frontend_wiring.py -q
```

---

## Task 14 [DONE]: Docs And Operator Commands

**Files:**
- Modify: `README.md`
- Modify: `docs/index.md`
- Modify: `docs/getting-started.md`
- Modify: `docs/fleet.md`
- Modify: `docs/configuration.md`
- Modify: `docs/research/provider-refresh-audit-2026-08.md`
- Test: `tests/test_readme_generation.py`, `tests/test_docs_do_not_contradict_the_shipped_files.py`, `tests/test_configuration_reference.py`

**Interfaces:**

**Checkpoint:** Status [DONE]; Owner Codex; Started 2026-08-13; Evidence `133 passed` for docs/config/provider-source tests; Commit pending.

- Produces: docs that match shipped code and the canonical worker bootstrap.

- [x] Update provider counts and categories.
- [x] Document canonical worker bootstrap from `client command setup script.txt`.
- [x] Document auto-deploy toggle, delay, stable heartbeat threshold.
- [x] Document proxy pool lease/rotate behavior.
- [x] Document MYST wallet lease behavior and default password.
- [x] Document Settings credential sections.
- [x] Remove stale manual instructions that are no longer true.

**Verification:**

```powershell
pytest tests/test_readme_generation.py tests/test_docs_do_not_contradict_the_shipped_files.py tests/test_configuration_reference.py -q
```

---

## Task 15 [DONE]: Local Full Verification

**Files:**
- No direct edits unless tests expose drift.
- Test: full targeted suite and full suite if feasible.

**Interfaces:**

**Checkpoint:** Status [DONE]; Owner Codex; Started 2026-08-13; Evidence `680 passed, 1 skipped` plus `python scripts/check_deploy_baseline.py` passed; Commit be8d144; Push done.

- Produces: commit-ready repo state.

- [x] Run targeted suite:

```powershell
pytest tests/test_catalog.py tests/test_catalog_loader.py tests/test_collectors.py tests/test_collector_contracts.py tests/test_main_routes.py tests/test_readme_generation.py tests/test_proxy_egress.py tests/test_proxy_routes.py tests/test_worker_keys.py tests/test_worker_myst_sync.py tests/test_worker_keys.py tests/test_frontend_wiring.py tests/test_myst_wallets_module.py tests/test_myst_runtime.py tests/test_worker_myst_sync.py tests/test_provider_automation.py tests/test_provider_installers.py tests/test_runtime_assets.py tests/test_deploy_credentials.py tests/test_payout_earnings.py tests/test_payout_reconcile.py -q
```

- [x] Run deploy baseline:

```powershell
python scripts/check_deploy_baseline.py
```

- [x] Run full suite when time permits:

```powershell
pytest -q
```

---

## Task 16 [DONE]: Commit, Push, Deploy, Smoke

**Files:**
- Modify only if deployment exposes a real code/docs gap.
- Test: VPS server health and browser smoke.

**Interfaces:**

**Checkpoint:** Status [DONE]; Owner Codex; Started 2026-08-13; Evidence local `be8d144`, GitHub pushed, VPS deployed, UI/worker healthy, no CI runs listed for branch; Commit be8d144.

- Produces: GitHub and VPS server synchronized to the correct branch/commit.

- [x] Confirm branch is `provider-standard-40834f6`.
- [x] Confirm no unrelated dirty files are included.
- [x] Commit with a scoped message.
- [x] Push to GitHub.
- [x] Check GitHub CI.
- [x] Deploy VPS server from GitHub.
- [x] Do not touch existing VPS server DB/volumes.
- [x] Smoke-check Dashboard, Setup Wizard, Service Catalog, Payouts, Proxy Provider, Proxy Pool, MYST Wallet, Settings, Fleet.
- [x] Recreate Adnade or selected provider nodes from VPS server to worker, not direct worker SSH.
- [x] Confirm local, GitHub, and VPS server commits match.

**Verification:**

```powershell
git status --short
git log --oneline -1
```

---

## Task 17 [IN_PROGRESS]: Active Provider Runtime Normalization

**Files:**
- Modify: `app/provider_modes.py`
- Modify: `app/main.py`
- Modify: `app/orchestrator.py`
- Modify: `app/worker_api.py`
- Modify: `services/bandwidth/*.yml`
- Modify: `services/depin/*.yml`
- Reference only: `D:\1. WORK_true\CashPilot\provider-runtime\provider_code_setup_node\*.py`
- Test: provider runtime/mode/deploy contract tests.

**Interfaces:**

**Checkpoint:** Status [DONE]; Owner Codex; Started 2026-08-15; Evidence `1242 passed, 7 skipped`; `python scripts/check_deploy_baseline.py` passed; Commit pending.

- Produces: active 18 providers can be represented as direct, proxy, or both runtime instances without name/volume/container collisions.

- [x] Read every manual provider setup script under `provider-runtime/provider_code_setup_node`.
- [x] Build the source-of-truth provider mode matrix from manual scripts and catalog YAML.
- [x] Fix any wrong `direct`, `proxy`, or `both` classification.
- [x] Add tests that every active catalog provider has supported modes and rejected unsupported modes.
- [x] Add tests that `both` expands to two unique instance IDs.
- [x] Add tests that proxy-mode deployment attaches a proxy and direct-mode deployment does not.
- [x] Keep EarnApp proxy-only and non-Docker constraints explicit.
- [x] Keep MYST direct-only with wallet lease separate from proxy pool.
- [x] Run local full verification.
- [ ] Commit, push, deploy VPS from GitHub, verify CI and container health.

**Verification:**

```powershell
pytest tests/test_provider_modes.py tests/test_main_routes.py tests/test_proxy_routes.py tests/test_worker_keys.py -q
pytest -q
```

---

## Self-Review

- Spec coverage: all 18 active providers, Dashboard, Setup Wizard, Service Catalog, Payouts, Proxy Provider, Proxy Pool, MYST Wallet, Settings, Fleet, auto-deploy, proxy lease, MYST lease, worker heartbeat, Chrome credential audit, docs, commit/push/deploy are covered.
- Redundant logic removed: separate MYST heartbeat and generic unused asset abstractions are not part of the final design.
- Type consistency: credential groups remain Deploy runtime, Earnings collector, Dashboard / session; runtime truth remains worker heartbeat plus provider_states; proxy lease remains worker-level; MYST wallet lease remains server asset inventory.
