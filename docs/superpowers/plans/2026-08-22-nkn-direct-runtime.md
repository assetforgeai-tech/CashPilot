# NKN Direct Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task, and use `test-driven-development` for every production behavior.

**Goal:** Add an official `nknorg/nkn:latest` direct runtime that discovers one public-IPv4 slot per node, leases one exclusive NKN wallet per slot, reports runtime/balance evidence, and can be deployed sequentially to a worker without changing existing providers.

**Architecture:** The server remains the wallet/lease authority and sends a per-slot deployment specification to the worker. Bootstrap prepares host networking and persistent limits; it does not deploy providers. The worker creates one isolated bridge/network and one named volume per slot, seeds the exact tested NKN config and wallet material before starting the official image, and reports redacted evidence on heartbeat. NKN is added as a direct-only catalog/runtime provider and is special-cased in auto-deploy so legacy provider behavior remains unchanged.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLite/aiosqlite, Docker SDK, httpx, shell bootstrap, pytest/pytest-asyncio, YAML catalog.

## Global Constraints

- Do not modify, redeploy, rotate, or remove any provider marked `PROTECTED_DONE`; MYST remains direct-only and Grass remains retired.
- Do not change the server-local `dev` worker image in this feature.
- Do not expose wallet JSON, wallet password, beneficiary secrets, API keys, or raw credentials in logs, heartbeats, dashboard responses, commits, or tests.
- One public IPv4 slot maps to exactly one NKN instance and one exclusive wallet lease.
- Deploy slots and providers sequentially; an individual failure is recorded and must not prevent later slots/providers from attempting deployment.
- A failed deploy retains its wallet lease for retry; a deliberate remove releases it; a worker missing for 15 minutes triggers reclaim with assignment-version/CAS protection.
- Each NKN container uses `restart: always`, at most one CPU and 1 GiB RAM, a private named volume, and the exact tested config keys (`BeneficiaryAddr`, `beneficiaryAddr`, `SyncMode`, `PasswordFile`).
- Live mutation is limited to a read-only snapshot followed by an isolated NKN canary on `test-sing`; no existing NKN/npool node or other provider is recreated.

### Task 1: Lock interfaces and add public-IP slot/bootstrap primitives

**Files:**
- Create: `app/public_ip_slots.py`
- Create: `scripts/bootstrap-worker.sh`
- Modify: `app/worker_api.py`
- Test: `tests/test_public_ip_slots.py`, `tests/test_bootstrap_contract.py`

- [ ] Add failing tests for strict slot normalization (IPv4 only, unique public IPs, stable `slot_id`, no echo-IP multiplication), Azure IMDS precedence, and single-IP fallback.
- [ ] Add failing tests for bootstrap contract text: bridge per slot, SNAT/private-IP mapping, ports `30000-30005` TCP/UDP, `LimitNOFILE=1048576`, idempotence, and no credential literals.
- [ ] Implement pure slot parsing/discovery helpers returning serializable slot records and an explicit `route_ready`/`source` state; never guess missing private IP or gateway.
- [ ] Implement the tracked bootstrap script with `set -euo pipefail`, Docker/ufw prerequisites, persistent systemd preparation, bridge/SNAT setup, and a JSON state file consumed by the worker. Keep the external credential-bearing command file untouched.
- [ ] Expose worker read-only `/api/network/slots` and load the state file without mutating host routes during provider deploy.
- [ ] Run focused tests and shell syntax checks.

### Task 2: Add NKN catalog/runtime and worker deployment primitives

**Files:**
- Create: `services/bandwidth/nkn.yml`
- Create: `app/nkn_runtime.py`
- Modify: `app/provider_runtime.py`, `app/catalog.py`, `app/worker_api.py`
- Test: `tests/test_nkn_runtime_contract.py`, `tests/test_worker_deploy_contract.py`

- [ ] Add failing tests for direct-only catalog metadata, official image, exact config, critical volume, allowed ports/device/network policy, and resource limits.
- [ ] Add a dedicated NKN worker endpoint/runtime instead of widening the generic provider deploy surface. It must seed wallet/config into a slot volume before container start, require the bootstrap-owned slot bridge, bind the slot private IP to ports, set `nano_cpus=1_000_000_000`, `mem_limit=1g`, `restart_policy=always`, and label `instance_id`, `slot_id`, and wallet assignment version.
- [ ] Keep wallet material only on the worker volume/state path; return redacted metadata and container ID.
- [ ] Add explicit NKN remove lifecycle (no stop action) and protect unrelated critical volumes.
- [ ] Run focused worker/orchestrator tests and catalog validation.

### Task 3: Implement exclusive NKN wallet lease/CAS/reclaim lifecycle

**Files:**
- Modify: `app/database.py`, `app/main.py`
- Test: `tests/test_nkn_wallet_leases.py`

- [ ] Add failing tests for exclusive lease by `(worker, slot)`, no duplicate active wallet/address, retry retaining the same lease, deliberate release, 15-minute stale reclaim, and stale-worker reclaim response carrying wallet/version/token.
- [ ] Implement `lease_nkn_wallet`, `release_nkn_wallet`, `reclaim_stale_nkn_wallets`, and assignment-version CAS helpers using `BEGIN IMMEDIATE`; preserve existing import/list redaction.
- [ ] Add per-slot instance records and deployment tombstones so auto-deploy is idempotent and a failed slot does not block later slots.
- [ ] Integrate NKN-specific deploy/remove paths in `api_deploy`, `_svc_remove`, and stale-worker checks without changing MYST wallet functions.
- [ ] Run lease/database regression tests plus existing MYST/proxy tests.

### Task 4: Add NKN heartbeat/evidence and official RPC collector

**Files:**
- Create: `app/collectors/nkn.py`
- Modify: `app/collectors/__init__.py`, `app/worker_api.py`, `app/main.py`
- Test: `tests/test_nkn_collector.py`, `tests/test_worker_nkn_sync.py`

- [ ] Add failing tests for parsing official `getbalancebyaddr` JSON-RPC (`amount` in NKN), bounded timeout/error-to-unknown behavior, and local `getnodestate` evidence (`PERSIST_FINISHED` plus running container).
- [ ] Implement the collector against `https://mainnet-rpc-node-0001.nkn.org/mainnet/api/wallet`; use only the beneficiary address from Settings and never scrape HTML or log credentials.
- [ ] Extend heartbeat payload with redacted NKN instance state (instance/slot, wallet ID/version, public IP, runtime/evidence) and implement server-side sync plus dashboard summary fields for beneficiary balance and online/offline counts.
- [ ] Reclaim only after the configured 15-minute worker staleness threshold; suspend locally at 14 minutes without a server ACK, preserve identity for a valid resume, and reject stale assignment versions at the worker.
- [ ] Run collector, heartbeat, and fleet/dashboard tests.

### Task 5: Sequential NKN auto-deploy and Settings/Fleet surfaces

**Files:**
- Modify: `app/main.py`, `app/worker_api.py`, `app/templates/settings.html`, `app/templates/fleet.html`, `app/templates/dashboard.html`, `app/static/js/app.js`
- Test: `tests/test_nkn_auto_deploy.py`, `tests/test_nkn_dashboard.py`

- [ ] Add failing tests proving NKN runs once per worker/slot in slot order, continues after a slot failure, does not repeat after a successful heartbeat, and leaves all legacy provider ordering/results unchanged.
- [ ] Implement a small NKN scheduler branch behind the existing stable-worker auto-deploy flag; use worker-reported slots and server lease CAS, not a global deployment row.
- [ ] Add only the beneficiary-address Settings input and redacted NKN inventory/runtime cards; render NKN balance in `NKN` and online/offline counts without changing existing provider cards.
- [ ] Add API contract tests for authenticated Settings/Fleet responses and secret masking.
- [ ] Run full targeted auto-deploy/UI suite.

### Task 6: Documentation, impact audit, and quality gates

**Files:**
- Modify: `docs/configuration.md`, `docs/fleet.md`, `docs/ACTIVE_CONTEXT.md`, `docs/research/contract-test-index.md`, `docs/research/repo-github-understanding.md`
- Test/tools: `scripts/check_deploy_baseline.py`, `scripts/check_catalog_liveness.py`, `ruff`, `pytest`

- [ ] Document bootstrap/runtime boundary, slot/bridge contract, wallet lifecycle, evidence, collector RPC, and NKN-only canary rollback.
- [ ] Update provider matrix to mark NKN `FOCUS_NKN` until live evidence; do not alter protected-provider rows.
- [ ] Run `pytest`, `ruff check`, `ruff format --check`, `compileall`, `git diff --check`, deploy-baseline, docs/credential scans, and `understand-diff`; compare provider YAML hashes before/after.
- [ ] Stop and fix any regression or unexpected protected-provider diff before release.

### Task 7: PR/release and isolated test-sing canary

**Files/operations:**
- GitHub PR/Actions and release workflow
- VPS read-only snapshot, then only NKN canary on `test-sing`

- [ ] Before any mutation, snapshot server/test-sing worker identity, container IDs/restarts, NKN/npool containers, port occupancy, wallet rows, and database backup; preserve the three known untracked compose files.
- [ ] Commit and open a PR; wait for required CI and review the impact diff. Publish UI/worker images only if the changed paths require them; do not upgrade server-local `dev`.
- [ ] Upgrade only the test-sing worker component required for NKN, deploy one fresh slot canary with a fresh wallet/volume, and leave existing NKN/npool and all other providers untouched.
- [ ] Verify lease/version, exact config, public IP, bridge/ports, CPU/RAM/restart policy, official logs, local node state, heartbeat, beneficiary balance, and dashboard online count.
- [ ] Roll back only the canary on failure; release its lease only after deliberate removal. Update `ACTIVE_CONTEXT` and mark NKN `PROTECTED_DONE` only when all evidence is captured.

## Completion Checklist

- [ ] All new tests observed RED before implementation and GREEN afterward.
- [ ] Full suite and static/documentation gates pass with no protected-provider diff.
- [ ] PR CI passes and release image manifests are verified.
- [ ] Test-sing canary evidence is recorded without secret material.
- [ ] No unapproved server/live-provider mutation occurred.
