# Provider Topology Production Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make direct-only, direct+proxy, and proxy-only providers production-ready with deterministic capacity, isolated lifecycle, explicit egress policy, and verifiable reconciliation.

**Architecture:** Keep the existing slot planner and provider runtime registry. Add one shared topology contract for readiness, capacity, egress, and lane state; keep provider-specific dedicated runtimes as adapters. Deploy sequentially, never fallback from proxy to direct, and reconcile each provider/mode/slot independently.

**Tech Stack:** Python, FastAPI/Pydantic, SQLite, Docker worker API, pytest, Ruff.

## Global Constraints

- Direct lanes use only the assigned public IPv4 slot.
- Proxy lanes use only the leased proxy egress and fail closed; no direct fallback.
- Hybrid lanes are independent; one lane failure cannot stop the other.
- Provider and node deployment remains sequential and failure-isolated.
- Unready direct slots remain visible in desired topology but are not mutated.
- Dedicated providers keep dedicated planners, but expose the same summary contract.
- Preserve unrelated user files and scheduler changes.

---

### Task 1: Preserve unready slots through generic topology planning

**Files:**
- Modify: `app/main.py:286-315, 3340-3375, 3590-3610`
- Test: `tests/test_provider_topology_api.py` (create if absent)

**Interfaces:**
- Add `_worker_public_ip_slots(worker_id, *, include_unready=False)`.
- Generic topology read/deploy planning calls `include_unready=True`; mutation filters `plan.deployable`.
- Dedicated NKN/EarnApp callers retain ready-only behavior unless explicitly opting in.

- [x] Write a failing API-level test showing an unready direct slot remains in `desired` and `blocked`, while a hybrid proxy plan remains deployable.
- [x] Run the focused test and verify failure caused by the current ready-only filtering.
- [x] Implement the optional filter without changing worker slot validation.
- [x] Run focused topology/API tests.
- [x] Run `git diff --check`.

### Task 2: Complete catalog egress contract

**Files:**
- Modify: all active provider YAML files under `services/bandwidth/` and `services/depin/` where missing `egress` metadata.
- Modify: `services/_schema.yml`
- Test: `tests/test_catalog_egress_contract.py`

**Interfaces:**
- Every provider declares `egress.mode`, `egress.udp`, `egress.fallback: none`, and a plain-English `reason`.
- `auto` is documented as policy selection only; it never permits unsafe direct fallback.

- [x] Add failing test requiring the contract for every `provider_runtime.PROVIDERS` entry.
- [x] Run test to confirm missing metadata is reported.
- [x] Add minimal metadata matching each runtime mode and UDP requirement.
- [x] Run catalog and schema tests.

### Task 3: Add shared lane-aware capacity and reconciliation summary

**Files:**
- Modify: `app/provider_topology.py`
- Modify: `app/main.py` topology response/reconciliation paths.
- Test: `tests/test_provider_topology.py`, `tests/test_provider_topology_api.py`

**Interfaces:**
- Summary exposes `desired`, `deployable`, `blocked`, `running`, `missing`, `retry`, `pending_proxy`, and per-lane counts.
- A proxy shortage is `pending_proxy`, never successful deployment.
- Direct route mismatch is a verification failure, not a healthy running node.

- [x] Add failing unit tests for direct blocked, hybrid partial, and proxy shortage summaries.
- [x] Implement minimal summary fields and preserve existing response keys.
- [x] Run focused tests.

### Task 4: Enforce lane-isolated lifecycle and egress verification

**Files:**
- Modify: `app/provider_network_audit.py`
- Modify: `app/main.py` lifecycle/reconciliation helpers.
- Modify: `app/provider_runtime.py` lifecycle metadata.
- Test: `tests/test_provider_network_audit.py`, lifecycle tests.

**Interfaces:**
- Lifecycle key is `(provider, worker, instance, mode, slot)`.
- Direct failures restart/reconcile only the direct lane.
- Proxy failures rotate only the proxy lane and release lease only after verified replacement/ACK.
- Missing container requires fresh worker inventory before any cleanup.

- [x] Add failing tests proving direct and proxy egress mismatches are attention-worthy.
- [x] Implement the smallest lane-scoped dispatch changes.
- [x] Run lifecycle/network tests.

### Task 5: Verify actual egress and capacity before enabling deployment

**Files:**
- Modify: `app/main.py` preflight/reconciliation response.
- Modify: worker API contract only if required for slot/egress evidence.
- Test: `tests/test_capacity_preflight.py`, `tests/test_provider_topology_api.py`
- Docs: `docs/evidence/provider-topology-production-readiness.md`

**Interfaces:**
- Preflight reports CPU, RAM, disk, ports, IPv4 slots, proxy capacity, and `pending_capacity`.
- Healthy means inventory confirmed, container present, assigned egress verified, and no leak finding.
- Auto-deploy remains disabled until read-only dry-run and sequential canary evidence pass.

- [x] Add failing preflight tests for insufficient proxy capacity and expose `pending_capacity` in topology summary.
- [x] Implement proxy-capacity aggregation in the read-only provider plan endpoint without destructive cleanup.
- [x] Run full test suite, Ruff, compileall, and diff check.
- [ ] Record evidence for workers `112444` and `112494` via worker API/SSH only.
- [ ] Run sequential canary: direct-only, hybrid, proxy-only; verify reboot, rerun, failure isolation, lease/release, and egress.
- [ ] Enable scoped auto-deploy only after evidence passes.

### Task 6: Release verification

**Files:**
- Modify: `.github/workflows/release.yml` to remove unreachable legacy code after deferred exit.
- Verify: PR `#303`, PR `#304`, `main` compose pins, release digest.

- [x] Remove dead workflow code.
- [ ] Rebase and run fresh checks.
- [ ] Merge only with required checks; no admin bypass.
- [ ] Verify deployed server/worker digest and record redacted evidence.

### Task 7: Scope proxy capacity and topology policy

**Files:**
- Modify: `app/database.py`, `app/main.py`, `app/provider_runtime.py`, `app/provider_topology.py`
- Test: `tests/test_provider_capacity.py`, `tests/test_provider_topology.py`, `tests/test_provider_modes.py`

**Interfaces:**
- Capacity queries accept optional provider/group filters and never count a proxy that is leased, duplicate, sticky-owned, or unqualified.
- Catalog responses distinguish `topology` (`slot_direct`, `slot_both`, `slot_proxy`) from selected egress mode; `fallback` remains `none`.
- Proxy-only desired capacity is the minimum of ready public-IP slots and scoped qualified proxies; hybrid proxy capacity is calculated independently from direct capacity.

- [x] Add failing tests for scoped capacity.
- [x] Implement scoped capacity and topology summary fields.
- [x] Run focused tests and full static checks.
- [x] Add proxy-only minimum-capacity planning (read-only summary and deploy pending state).
- [ ] Capture live proxy-only minimum-capacity and egress evidence.
