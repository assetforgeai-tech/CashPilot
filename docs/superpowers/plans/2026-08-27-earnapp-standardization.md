# EarnApp Standardization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the verified single Mac canary into a production-safe EarnApp provider supporting VN Mac/iOS nodes and non-VN Ubuntu LXD nodes, with immutable identity, exclusive residential proxy lifecycle, account collection, sequential auto-deploy, recovery, and auditable live evidence.

**Architecture:** The CashPilot server remains authoritative for accounts, logical nodes, platform choice, encrypted identity profiles, proxy leases, and recovery generation. Workers execute one node at a time; Mac/iOS use the verified emulation runtime behind the existing sing-box sidecar, while Ubuntu runs the official EarnApp package inside a constrained LXD guest through a dedicated host-helper contract patterned after NKN. Existing EarnApp canary resources and every protected provider remain untouched until a release has passed local and CI verification.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic, SQLite/aiosqlite, Docker SDK, LXD REST helper, sing-box, pytest, JavaScript templates, GitHub Actions.

## Global Constraints

- Preserve the live Mac canary `earnapp-canary-test-sing-1`, its volume, identity, sidecar, account binding, proxy lease, and remote device.
- Preserve NKN, MYST, and every provider already marked `PROTECTED_DONE`; no bulk redeploy or cleanup.
- EarnApp is proxy-only. Every node receives one exclusive proxy that is alive, residential, has a canonical egress IP, and has the latest eligible `earnapp_wss` verdict.
- VN egress selects MacOS or iOS; non-VN egress selects Ubuntu LXD. Platform is generated once per logical node and never changes during restart, proxy rotation, recovery, or redeploy.
- Device IDs and encrypted identity profiles are generated once per logical node, are globally unique, and never appear in logs, public account APIs, or generic heartbeat payload fields beyond the non-secret device ID needed for evidence.
- Account assignment is least-assigned/evenly distributed. The account collector must use a live proxy already owned by one of that account's nodes.
- Worker heartbeat loss starts `RECOVERY_HOLD` for exactly 3600 seconds. Recovery prefers the prior proxy/account/device/platform, but may rotate only that node's proxy when the old egress is unusable.
- Never automatically unlink or delete a remote EarnApp device.
- Deploy providers sequentially and nodes within EarnApp sequentially. A failed node is recorded and skipped; it cannot block later nodes or providers.
- Do not commit proprietary runtime binaries, captured profiles, proxy credentials, account tokens, or live identifiers.

---

### Task 1: Schema v20 and immutable logical-node contracts

**Files:**
- Modify: `app/database.py`
- Modify: `tests/test_earnapp_account_pool.py`
- Modify: `tests/test_earnapp_recovery.py`

**Interfaces:**
- `earnapp_logical_nodes.platform` stores one of `macos`, `ios`, or `ubuntu`.
- A partial unique index enforces uniqueness for non-empty `device_id` values.
- `assign_earnapp_account(logical_node_id, *, platform="")` creates a node once and rejects an attempted platform change.
- Migration from schema v19 preserves account IDs, node IDs, leases, generations, worker bindings, device IDs, and proxy IDs.

- [ ] **Step 1: Write schema and migration tests that assert platform persistence and non-empty device uniqueness.**
- [ ] **Step 2: Run the focused tests and verify they fail because schema v19 lacks the column/index and immutable-platform checks.**
- [ ] **Step 3: Add the v20 column, partial unique index, strict schema metadata, safe table rebuild logic, and migration.**
- [ ] **Step 4: Add collision errors before provisioning and keep empty legacy device IDs valid.**
- [ ] **Step 5: Run all EarnApp account/recovery migration tests and verify green.**

### Task 2: Cross-platform identity registry

**Files:**
- Modify: `app/earnapp_runtime.py`
- Modify: `app/earnapp_canary.py`
- Create: `app/earnapp_identity.py`
- Modify: `tests/test_earnapp_canary_contract.py`
- Create: `tests/test_earnapp_identity.py`

**Interfaces:**
- `ensure_identity_profile(logical_node_id, platform) -> IdentityAsset` returns a persisted encrypted Mac/iOS profile or a persisted Ubuntu identity marker.
- Mac validates the full `mac_com.earnapp` contract and emits `sdk-mac-*`.
- iOS validates the Bright Rewards iOS contract and emits `sdk-ios-*`.
- Ubuntu emits an official-runtime UUID and stable machine ID for its LXD guest.

- [ ] **Step 1: Write failing tests for all required Mac/iOS fields, random uniqueness across nodes, and stability for retries.**
- [ ] **Step 2: Verify RED on missing iOS/Ubuntu generators and generic registry.**
- [ ] **Step 3: Implement platform-specific generators using cryptographic randomness and persisted encrypted profiles.**
- [ ] **Step 4: Validate the pinned source artifact hashes without adding runtime binaries to Git.**
- [ ] **Step 5: Run identity, canary, and runtime-asset tests.**

### Task 3: Immutable runtime supply chain and worker execution

**Files:**
- Modify: `app/earnapp_runtime.py`
- Create: `app/earnapp_lxd_runtime.py`
- Modify: `app/worker_api.py`
- Modify: `Dockerfile.worker`
- Modify: `scripts/build_earnapp_canary_image.py`
- Create: `scripts/install-earnapp-host-helper.sh`
- Create: `tests/test_earnapp_lxd_runtime.py`
- Modify: `tests/test_earnapp_canary_contract.py`
- Modify: `tests/test_runtime_assets.py`

**Interfaces:**
- Mac and iOS image manifests are content-addressed by source SHA-256 and expose required labels.
- Ubuntu deployment uses a narrow local host-helper API, LXD limits of 1 CPU/1024 MiB by default, official package discovery/download, stable guest identity, and no Docker socket inside the worker container.
- Worker state stores only redacted runtime evidence and never changes a node platform.

- [ ] **Step 1: Write failing image-label, iOS asset, Ubuntu LXD request, and redaction tests.**
- [ ] **Step 2: Verify RED for missing iOS image and LXD execution paths.**
- [ ] **Step 3: Implement content-addressed build manifests and separate Mac/iOS runtime contracts.**
- [ ] **Step 4: Implement the least-privilege EarnApp LXD host helper and worker client.**
- [ ] **Step 5: Run worker, runtime-asset, NKN-LXD regression, and protected-provider tests.**

### Task 4: Sequential planner and exclusive proxy lifecycle

**Files:**
- Create: `app/earnapp_deploy.py`
- Modify: `app/earnapp_recovery.py`
- Modify: `app/database.py`
- Modify: `app/main.py`
- Modify: `app/worker_api.py`
- Modify: `tests/test_auto_deploy_policy.py`
- Create: `tests/test_earnapp_auto_deploy.py`
- Modify: `tests/test_earnapp_recovery.py`

**Interfaces:**
- `plan_worker_nodes(worker_id, public_ipv4_slots) -> list[EarnAppNodePlan]` targets one proxy node per public IPv4 slot.
- Platform selection derives from the leased proxy's normalized country: VN randomly selects and then persists `macos` or `ios`; all other countries persist `ubuntu`.
- `deploy_worker_nodes_sequentially` awaits each node and returns per-node success/failure without raising an aggregate failure.
- Proxy health failure rotates only the affected logical node and honors the prior proxy preference when it becomes eligible again.

- [ ] **Step 1: Write failing tests for slot count, country/platform mapping, exclusive leases, sequential execution, and failure isolation.**
- [ ] **Step 2: Verify RED on the absent planner and generic auto-deploy exclusion.**
- [ ] **Step 3: Implement planner/provisioning with server-side locks and no worker-level proxy assignment.**
- [ ] **Step 4: Integrate EarnApp after protected providers in auto-deploy without changing their code paths.**
- [ ] **Step 5: Add worker ping-based proxy health evidence and server rotation decisions.**
- [ ] **Step 6: Run auto-deploy, proxy, recovery, Fleet, and protected-provider regression tests.**

### Task 5: Account collector, token health, and operator UI

**Files:**
- Modify: `app/earnapp_collection.py`
- Modify: `app/collectors/earnapp.py`
- Modify: `app/routers/earnapp_accounts.py`
- Modify: `app/templates/settings.html`
- Modify: `app/static/js/app.js`
- Modify: `app/static/css/style.css`
- Modify: `tests/test_earnapp_collector.py`
- Modify: `tests/test_earnapp_account_routes.py`
- Create: `tests/test_earnapp_settings_ui.py`

**Interfaces:**
- Scheduled collection runs per active account through a live proxy assigned to that account.
- Account payload reports balance, lifetime earnings, online/offline nodes, token expiry state, last collection, and proxy route health without returning secrets.
- Dashboard places expired/expiring token and low/empty leaseable-proxy alerts above the account inventory.

- [ ] **Step 1: Write failing tests for account-scoped routing, expiry thresholds, scheduled collection, and secret-free API/UI output.**
- [ ] **Step 2: Verify RED for missing scheduler/status fields.**
- [ ] **Step 3: Implement scheduled collection and route failover using only that account's node proxies.**
- [ ] **Step 4: Improve Settings/Fleet UI copy, status hierarchy, and responsive tables.**
- [ ] **Step 5: Run collector, router, settings, and template tests.**

### Task 6: Release boundary and CI verification

**Files:**
- Modify only if tests require it: `.github/workflows/test.yml`
- Modify only if release routing requires it: `.github/workflows/release.yml`
- Modify: `docs/guides/earnapp.md`

**Interfaces:**
- CI runs the complete EarnApp contract suite and protected-provider regressions.
- Release publishes only CashPilot UI/worker images; proprietary EarnApp runtime assets remain a separately authorized, content-addressed operator artifact.

- [ ] **Step 1: Run focused tests, full pytest, Ruff, compileall, and `git diff --check`.**
- [ ] **Step 2: Audit the diff for NKN/MYST/protected-provider modifications and explain every shared-module change.**
- [ ] **Step 3: Verify GitHub Actions workflow path filters build every changed CashPilot component.**
- [ ] **Step 4: Commit, open PR, wait for CI, review the final PR diff, and merge only when all required checks pass.**
- [ ] **Step 5: Create the release and verify image manifests plus code signatures/content from the registry.**

### Task 7: Fresh-worker live validation and recovery matrix

**Files:**
- Modify after evidence: `docs/ACTIVE_CONTEXT.md`
- Modify after evidence: `docs/research/repo-github-understanding.md`

**Interfaces:**
- Live validation uses `vps/vps-test-sing.txt`, direct SSH, and no Azure CLI.
- Existing Mac canary is inspect-only. New tests use fresh logical nodes, volumes, identities, sidecars, and proxy leases.

- [ ] **Step 1: Read-only preflight worker release, public IPv4 slots, LXD helper, account pool, proxy capacity, and existing canary resources.**
- [ ] **Step 2: Deploy one new platform-appropriate node sequentially and verify container/LXD state, egress, heartbeat, and authenticated EarnApp devices evidence.**
- [ ] **Step 3: Verify restart/reboot preserves identity, account, platform, volume, and proxy preference.**
- [ ] **Step 4: Simulate only the new canary's proxy failure, verify isolated rotation, then verify recovery preference without remote unlink/delete.**
- [ ] **Step 5: If capacity permits, validate a second platform with a separate node/proxy and confirm device IDs differ.**

### Task 8: Closeout and provider protection

**Files:**
- Modify: `docs/ACTIVE_CONTEXT.md`
- Modify: `docs/guides/earnapp.md`
- Modify: `docs/research/repo-github-understanding.md`

**Interfaces:**
- EarnApp changes to `PROTECTED_DONE` only after local tests, CI, release, registry verification, authenticated device evidence, heartbeat, restart persistence, and isolated proxy rotation all pass.

- [ ] **Step 1: Record exact release, worker, logical-node, account, proxy, egress, platform, device, and timestamp evidence without secrets.**
- [ ] **Step 2: Document rollback procedures that preserve identities, volumes, accounts, and leases.**
- [ ] **Step 3: Run a final read-only baseline audit and list any residual non-blocking risks.**
- [ ] **Step 4: Mark EarnApp `PROTECTED_DONE` only if every acceptance criterion is evidenced; otherwise leave it explicitly open with the exact failed gate.**
