# EarnApp Multi-Platform Production Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with review checkpoints.

**Goal:** Enable EarnApp MacOS/iOS emulation for qualified VN residential proxies and Ubuntu x64/LXD for qualified non-VN residential proxies, with sequential multi-node canaries and immutable protected baselines.

**Architecture:** Keep the server authoritative for platform selection, account binding, identity, proxy lease, lifecycle and workload evidence. Route MacOS/iOS through the existing dedicated EarnApp platform canary/runtime contract and Ubuntu through the existing restricted LXD contract; generic catalog/raw Docker routes remain closed. Every node gets a unique identity, volume, logical ID and exclusive residential egress.

**Tech Stack:** Python/FastAPI, SQLite, Docker runtime artifacts, LXD host helper, pytest, Ruff, existing EarnApp identity/canary/recovery modules.

## Global Constraints

- VN residential proxy selects `macos` or `ios`; non-VN residential proxy selects `ubuntu` with `runtime_backend=lxd`.
- Existing protected EarnApp nodes remain inspection-only; no identity, volume, account, lease or lifecycle mutation.
- Generic/raw Docker deploy cannot be used to bypass platform, proxy, identity or lease validation.
- Nodes are created sequentially and one failure must not block later provider/node work.
- Each node must prove unique identity, correct account link, authoritative online state, positive usage delta and restart persistence before closeout.
- No provider outside EarnApp may be changed by this plan.

### Task 1: Establish the authoritative platform/proxy contract

**Files:**
- Modify: `app/provider_runtime.py`
- Modify: `app/earnapp_runtime.py`
- Test: `tests/test_earnapp_runtime_policy.py`
- Test: `tests/test_earnapp_ubuntu_policy.py`

**Interfaces:**
- `provider_runtime.platform_deployment_allowed(slug, platform, runtime_backend)` remains the single policy predicate.
- Add a pure helper that accepts normalized proxy country/residential status and returns the allowed platform set.

- [ ] Write failing tests proving VN residential allows only MacOS/iOS, non-VN residential allows only Ubuntu/LXD, non-residential is rejected, and protected node IDs remain blocked.
- [ ] Run the focused policy tests and confirm they fail because current policy only allows Ubuntu/LXD.
- [ ] Implement the smallest normalized geo-platform policy without changing generic route behavior.
- [ ] Run focused tests and confirm they pass.

### Task 2: Restore dedicated MacOS/iOS canary routing

**Files:**
- Modify: `app/main.py`
- Modify: `app/worker_api.py`
- Modify: `app/earnapp_canary.py`
- Test: `tests/test_earnapp_canary_contract.py`
- Test: `tests/test_earnapp_host_agent.py`

**Interfaces:**
- Dedicated canary route validates platform, proxy qualification, identity and account before calling platform-specific worker deployment.
- Generic `/api/containers/{slug}/deploy` and raw worker Docker paths continue to fail closed for EarnApp.

- [ ] Write failing tests for MacOS and iOS dedicated deployment with VN residential proxy metadata and for rejection of non-VN/unsupported backend.
- [ ] Run tests to verify the expected failures.
- [ ] Implement route validation and platform-specific artifact selection using existing identity/runtime helpers.
- [ ] Run focused tests and confirm protected baseline aliases are still rejected before worker calls.

### Task 3: Enforce multi-node sequential allocation and evidence

**Files:**
- Modify: `app/earnapp_deploy.py`
- Modify: `app/earnapp_canary.py`
- Modify: `app/main.py`
- Test: `tests/test_earnapp_auto_deploy.py`
- Test: `tests/test_earnapp_node_health.py`

- [ ] Write failing tests for one-node-per-ready-slot planning, unique proxy egresses, balanced account assignment, continue-on-node-failure, and positive usage as a closeout gate.
- [ ] Run tests and verify failures are contract failures rather than fixture errors.
- [ ] Implement sequential scheduling and per-node result isolation using existing DB/CAS/recovery primitives.
- [ ] Run focused tests and confirm no protected node is selected or mutated.

### Task 4: Complete identity/artifact compatibility checks

**Files:**
- Modify: `app/earnapp_identity.py`
- Modify: `app/earnapp_runtime.py`
- Modify: `Dockerfile.worker`
- Test: `tests/test_earnapp_identity.py`
- Test: `tests/test_catalog_loader.py`

- [ ] Add failing tests for audited Mac/iOS metadata fields, unique persisted IDs, artifact manifest hashes and worker-image inclusion.
- [ ] Run tests to verify missing fields or supply-chain checks fail.
- [ ] Extend only newly generated profiles; never rewrite existing protected profile bytes.
- [ ] Run identity/catalog tests and verify the worker image copies the policy/runtime modules.

### Task 5: Documentation and canary runbook

**Files:**
- Modify: `docs/guides/earnapp.md`
- Modify: `docs/ACTIVE_CONTEXT.md`
- Create: `docs/research/earnapp-multi-platform-production-audit-2026-08.md`

- [ ] Document the geo-platform matrix, sequential canary matrix, evidence requirements, rollback and protected nodes.
- [ ] Record unresolved live hypotheses separately from source-policy decisions.
- [ ] Validate documentation links and ensure no credential/token is written.

### Task 6: Verification gate

- [ ] Run focused EarnApp tests.
- [ ] Run full `pytest`.
- [ ] Run `ruff check .`, `ruff format --check .`, `python -m compileall app tests`, JavaScript syntax checks and `git diff --check`.
- [ ] Run changed-diff secret scan and inspect `Dockerfile.worker` manually because Docker is unavailable on Windows.
- [ ] Stop before commit, PR, release, deployment or live canary unless separately authorized after the source gate passes.

## Risks and rollback

- A policy change could accidentally reopen generic deployment; route-level regression tests must assert generic/raw Docker remains blocked.
- Existing profile/identity bytes are immutable; only fresh canary IDs may use expanded metadata.
- Live canaries must be isolated by logical ID, proxy lease, egress IP, volume and account binding. Rollback is node-local and must not touch protected baselines.
