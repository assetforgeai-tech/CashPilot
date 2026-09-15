# Full Azure Production Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Validate and harden CashPilot end-to-end on only Azure workers `118903` and `118904`, deploying every supported provider topology and producing provider/runtime/dashboard evidence before production release.

**Architecture:** Keep provider truth in the catalog/runtime adapters, topology cardinality in the existing planner, lifecycle/lease decisions in existing APIs, and live evidence in immutable cycle manifests. Generic providers use slot deployment; dedicated/manual providers use their declared adapters only.

**Tech Stack:** Python, FastAPI, SQLite, Docker, PowerShell, pytest, existing CashPilot UI and provider dashboards.

## Global Constraints

- Never use `test-sing` or `test-us`.
- Only mutate Azure workers `118903` and `118904`, and only cycle-created provider resources.
- Do not expose credentials, tokens, cookies, or private provider data in evidence.
- Preserve identity volumes and leases unless a provider-specific lifecycle explicitly requires replacement.
- Do not infer current earnings from historical balances.
- Direct-only providers never lease proxies; proxy-only providers never fall back to direct egress.
- Dedicated/manual providers are not forced through generic Docker deployment.

---

### Task 1: Fix rollout script transport warning

**Files:**
- Modify: `codex-scratch/azure_worker_upgrade_v15018.ps1`
- Modify: `codex-scratch/_tmp_upgrade_server_ui_v15018.ps1`
- Test: shell output from a dry-run script generation

- [x] Remove UTF-8 BOM from generated remote shell payload using ASCII/base64 transport before transport.
- [x] Verify remote output has no `﻿set: command not found`.

### Task 2: Build authoritative Azure cycle manifest

**Files:**
- Create: `codex-scratch/azure_full_cycle_manifest.py`
- Create: `docs/evidence/azure-cycle-2026-09-14-cycle-1.json`

- [x] Query only workers `118903,118904` and record provider, lane, slot, container, image, mounts, restart count, lease, and expected egress.
- [x] Mark provider topology as generic, dedicated, or manual from `provider_runtime.py`.
- [x] Fail if a result includes a non-Azure worker or a credential value.

### Task 3: Deploy supported generic topology

**Files:**
- Modify: `codex-scratch/deploy_azure_provider_cycle.py`
- Test: `tests/test_provider_slot_deploy.py`

- [x] Use the current catalog spec for every generic slot.
- [x] Run deployment sequentially per worker/provider and save HTTP/result evidence.
- [ ] Treat partial/blocked plans as explicit evidence, not deployment success.
- [x] Verify no restart loop and no stale endpoint after deployment.
- [x] Keep Spide collector dashboard-only; never execute collector code in the node.
- [x] Pin Spide bootstrap to the R2 ZIP and verified executable SHA.
- [x] Reconcile and refresh any worker container still using the legacy DigitalOcean bootstrap.

Live defect fixes added during cycle 1:

- [x] Detect recent Docker restart loops as degraded instead of running.
- [x] Make Proxies.sx SDK acquisition retrying, atomic, and fail-closed.
- [x] Restore Spide raw account login plus form-encoded Device-key registration.

### Task 4: Exercise dedicated provider adapters

**Files:**
- Modify only adapter files if a demonstrated defect blocks their declared flow.
- Test: existing dedicated-provider tests plus one regression per defect.

- [ ] Inspect readiness for `mysterium`, `nkn`, `proxybase-xyz`, `uprock`, and `wipter`.
- [ ] Run only supported dedicated/manual flows with existing credentials and preserve identity storage.
- [ ] Record unsupported/manual states rather than inventing generic deployment.

### Task 5: Reconcile runtime, database, and lease state

**Files:**
- Create: `docs/evidence/azure-runtime-reconciliation-2026-09-14.md`

- [x] Compare worker heartbeat inventory, Docker inspect, `provider_instances`, active leases, and expected topology.
- [x] Detect restart-loop containers as unhealthy, not running.
- [x] Separate current Azure rows from legacy/global rows.

### Task 6: Network and provider proof

**Files:**
- Create: `docs/evidence/azure-network-provider-audit-2026-09-14.md`
- Create: `docs/evidence/azure-provider-dashboard-audit-2026-09-14.md`

- [ ] Probe direct IPv4, proxy IPv4, DNS, IPv6, UDP, DoH/DoT, and fallback per lane.
- [ ] Compare each provider's dashboard node/device state and observable traffic/usage delta.
- [ ] Redact all tokens, cookies, passwords, and account identifiers.

### Task 7: Reboot and lifecycle verification

**Files:**
- Create: `docs/evidence/azure-reboot-lifecycle-2026-09-14.md`
- Test: existing lifecycle and lease tests

- [x] Reboot each Azure worker once, preserving volumes and identities.
- [x] Verify heartbeat recovery and container restart policy; lease continuity and proxy rotation CAS remain under separate gate.
- [ ] Verify EarnApp-only usage/offline/banned policy does not affect other providers.

### Task 8: Clean cycle and repeat

**Files:**
- Modify: `codex-scratch/deploy_azure_provider_cycle.py` only if cleanup is demonstrably unsafe.
- Create: `docs/evidence/azure-cycle-2026-09-14-cycle-2.json`

- [ ] Snapshot evidence before cleanup.
- [ ] Remove only exact cycle-created resources; keep identity volumes and unrelated rows.
- [ ] Redeploy and repeat Tasks 2-7.
- [ ] Require two equivalent clean/deploy/reconcile passes before production gate.

### Task 9: Production gate report

**Files:**
- Create: `docs/evidence/azure-production-readiness-2026-09-14.md`

- [ ] Map every explicit requirement to fresh evidence or mark it incomplete.
- [ ] Report provider-specific gaps and residual risks.
- [ ] Do not mark production-ready until all required evidence is authoritative.

### Task 10: Provider separation and runtime drift gate

**Files:**
- Modify: `services/bandwidth/spide.yml`
- Modify: `provider-runtime/provider_code_setup_node/spide.py`
- Modify: `provider-runtime/provider_collector/spide.py`
- Test: `tests/test_catalog_loader.py`, `tests/test_provider_automation.py`

- [x] Runtime owns only CLI startup and device-key registration.
- [x] Collector remains manual/dashboard-only with an empty `collector_source`.
- [x] Never log dashboard credentials or device keys.
- [x] Verify the deployed executable SHA against the pinned R2 artifact.
- [x] Roll out the catalog/runtime to the stale worker container and capture process/path/hash evidence.
