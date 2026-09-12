# Provider Topology Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make direct-only, proxy-only, and direct+proxy providers production-ready with isolated capacity, safe lifecycle, auditable leases, and live evidence.

**Architecture:** Keep `app/provider_topology.py` as the pure planner and `app/provider_runtime.py` as the provider truth matrix. Add only the missing lifecycle/lease invariants around those contracts; dedicated NKN/Mysterium adapters remain separate. Verify each lane independently in code and on live workers.

**Tech Stack:** Python, FastAPI, SQLite, Docker Compose, pytest, Ruff, SSH/curl for live evidence.

## Global Constraints

- No direct/proxy cross-lane fallback.
- Unknown or zero proxy capacity fails closed.
- Direct nodes require a unique route-ready public IPv4 slot.
- Proxy nodes require one eligible, non-conflicting proxy egress lease.
- Runtime lease, sticky egress ownership, and account ownership are separate states.
- Preserve unrelated user artifacts and never use Azure CLI mutation.

---

### Task 1: Recover the Japan worker deployment

**Files:**
- Modify remote `/CashPilot/docker-compose.worker.yml` and `cashpilot-worker.service` only.
- Evidence: `docs/evidence/worker-1.40-live-2026-09-13.md`

- [ ] Verify the existing `cashpilot-worker` container name, image, volume, worker ID, and systemd failure.
- [ ] Stop/remove only that identified stale container; preserve its named data volume.
- [ ] Start Compose with `up -d --no-build`.
- [ ] Verify image `ghcr.io/assetforgeai-tech/cashpilot-worker:1.40`, runtime `1.40.0`, health 200, restart `always`, systemd active, and stable worker ID.
- [ ] Record redacted evidence and rollback details.

### Task 2: Add topology invariant tests before lifecycle changes

**Files:**
- Test: `tests/test_provider_topology.py`
- Test: `tests/test_provider_topology_api.py`

- [x] Add failing tests for direct-only refusing proxy targets, proxy-only not consuming IPv4 slots, and hybrid targets remaining independent.
- [x] Add tests for unavailable proxy capacity returning pending/blocked rather than shrinking desired topology.
- [x] Run focused tests and confirm expected failures.
- [x] Implement only the minimum planner/API changes if a gap is found.
- [x] Re-run focused tests.

Progress: proxy cardinality defaults to the authoritative bootstrap IPv4 count
when slot discovery is available. Explicit lane targets remain supported;
capacity shortage stays pending instead of shrinking desired topology. Direct
slot deploy fails closed without a slot manifest. Per-instance topology state
uses lane/slot-scoped volumes and device identity seeds.

Additional guard: hybrid planning retains its proxy target as blocked when
proxy discovery is unknown; it never silently collapses to direct-only.

### Task 3: Make lease selection deterministic and lane-scoped

**Files:**
- Modify: `app/database.py`, `app/routers/proxies.py`
- Test: `tests/test_provider_topology.py`, `tests/test_proxy_routes.py`

- [ ] Add failing tests proving one active lease per provider/worker/instance/lane and no duplicate active egress IP across lanes.
- [ ] Add deterministic ordering: eligible, healthy, unowned first; stable proxy ID tie-breaker.
- [ ] Preserve sticky ownership while releasing only the runtime lease.
- [x] Make rotation/release CAS-safe and idempotent.
- [x] Run focused lease tests.

Progress: provider lease release accepts an optional expected proxy ID and uses
compare-and-swap semantics, preventing stale cleanup/retry workers from
releasing a replacement lease. Existing callers remain backward compatible.

All deploy/bind failure cleanup callers now pass the proxy they acquired, so
late failures cannot release a newer rotation assignment.

Per-instance CAS replacement is now available for provider-scoped runtimes;
worker-level rotation remains reserved for legacy shared assignments until
the worker ACK contract exposes a provider-instance binding endpoint.

### Task 4: Normalize health and recovery policy

**Files:**
- Modify: `app/main.py`, `app/provider_network_audit.py`
- Test: `tests/test_earnapp_node_health.py`, `tests/test_provider_network_contracts.py`

- [ ] Add failing tests separating node offline, proxy dead, route unavailable, provider/account failure, and banned node.
- [ ] Apply restart-only recovery for transient node health failures.
- [ ] Apply proxy rotation only after verified proxy failure; never rotate due to account/dashboard lag alone.
- [ ] Keep provider/account failures from mutating unrelated nodes.
- [ ] Require complete leak evidence before healthy status.
- [ ] Run focused health tests.

### Task 5: Reconcile orphaned instances safely

**Files:**
- Modify: `app/database.py`, `app/main.py`
- Test: `tests/test_earnapp_lifecycle.py`, `tests/test_provider_topology.py`

- [ ] Verify the existing two-confirmation miss rule for generic providers.
- [ ] Add tests for runtime reappearance cancelling `missing_once`.
- [ ] Add tests ensuring EarnApp sticky ownership is retained during runtime absence.
- [ ] Ensure cleanup cannot release a lease while a live authenticated heartbeat still lists the instance.
- [ ] Run lifecycle tests.

### Task 6: Clarify topology/capacity UI

**Files:**
- Modify: `app/static/js/app.js`, `app/templates/*.html` as required.
- Test: `tests/test_frontend_wiring.py`

- [ ] Display direct and proxy desired/deployable/running/free/blocked counts independently.
- [ ] Display explicit pending reason for unknown/zero proxy capacity.
- [ ] Show lane and egress contract without implying fallback.
- [ ] Add browser-level checks for direct-only, proxy-only, and hybrid states.
- [ ] Run frontend wiring and browser verification.

### Task 7: Live lane canaries and evidence

**Files:**
- Evidence only: `docs/evidence/provider-topology-live-2026-09-13.md`

- [ ] Run direct-only canary on upgraded workers.
- [ ] Run proxy-only canary with a scoped eligible proxy.
- [ ] Run hybrid canary with explicit direct/proxy targets.
- [ ] Verify egress, lease uniqueness, restart/reboot persistence, rotation, release, and orphan reconciliation.
- [ ] Run IPv4/IPv6/DNS/UDP/DoH/DoT/direct-fallback probes per lane.
- [ ] Capture redacted commands, outputs, image digest, and rollback path.

### Task 8: Final verification and release gate

**Files:**
- Evidence: `docs/evidence/provider-topology-production-readiness-2026-09-13.md`

- [ ] Run full pytest suite, Ruff, compile checks, and frontend syntax checks.
- [ ] Re-poll PR CI for commit `b2e07139`.
- [ ] Compare every requirement against fresh evidence.
- [ ] Report remaining gaps; do not claim production readiness until all live gates pass.
