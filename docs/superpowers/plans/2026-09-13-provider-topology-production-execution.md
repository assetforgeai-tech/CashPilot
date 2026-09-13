# Provider Topology Production Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make direct-only, proxy-only, and hybrid providers production-ready with public-IPv4 cardinality, isolated leases, consistent lifecycle, fail-closed networking, and live evidence.

**Architecture:** Keep provider truth in `app/provider_runtime.py`, pure topology planning in `app/provider_topology.py`, lifecycle decisions in `app/provider_lifecycle.py`, and lease state in the existing database/API layer. Dedicated provider runtimes remain adapters; no lane may silently fall back to another egress mode.

**Tech Stack:** Python, FastAPI, SQLite, Docker, pytest, existing CashPilot runtime and browser UI.

## Global Constraints

- Bootstrap-detected public IPv4 slots are the authoritative desired node cardinality.
- Proxy capacity gates deployability; it never changes desired topology.
- Direct-only providers never lease proxies; proxy-only providers never use direct fallback.
- Hybrid providers keep independent direct and proxy lanes.
- Provider and node execution remain sequential; one failure cannot block later work.
- Proxy networking is fail-closed with explicit DNS, IPv6, UDP, DoH/DoT policy.
- Preserve user-owned `.tmp-*` artifacts and existing unrelated changes.
- Do not use Azure CLI; do not print credentials.

---

### Task 1: Enforce IPv4 cardinality for proxy lanes

**Files:**
- Modify: `app/provider_topology.py`
- Test: `tests/test_provider_topology.py`

**Interfaces:** `plan_provider_nodes(...)` keeps its existing signature. When no public IPv4 slots are supplied, proxy plans are pending instead of being inferred from `proxy_capacity`.

- [x] Add a failing test proving proxy-only with `public_ipv4_slots=[]` returns no deployable proxy plan and does not use `proxy_capacity` as desired cardinality.
- [x] Run `pytest tests/test_provider_topology.py -q` and observe the expected failure.
- [x] Change proxy target calculation to use `len(slots)` only; retain explicit `proxy_desired` as an operator target, with blocked plans when slot cardinality is unavailable.
- [x] Run the focused test and the topology suite; commit.

### Task 2: Normalize lane lease and ownership contract

**Files:**
- Modify: `app/provider_runtime.py`
- Modify: `app/database.py`
- Modify: `app/routers/proxies.py`
- Test: `tests/test_provider_topology.py`
- Test: `tests/test_proxy_pool.py`

**Interfaces:** Lease records expose provider, worker, instance, lane, proxy ID, and egress IP. Direct lanes return no proxy lease. EarnApp sticky ownership survives runtime release until account deletion.

- [ ] Add tests for direct-only no-lease, proxy-only scoped lease, hybrid direct/proxy isolation, and EarnApp sticky ownership.
- [ ] Run focused tests and confirm failures for missing invariants.
- [ ] Enforce lane/provider keys in lease queries and prevent direct-lane proxy assignment.
- [ ] Ensure release closes runtime lease without deleting EarnApp ownership; account deletion explicitly removes ownership.
- [ ] Run proxy/database tests; commit.

### Task 3: Unify lifecycle decisions

**Files:**
- Modify: `app/provider_lifecycle.py`
- Modify: `app/provider_runtime.py`
- Test: `tests/test_provider_lifecycle.py`

**Interfaces:** `decide_lane` remains the single decision entry point and returns `restart`, `rotate`, `blocked`, `recreate`, or `observe` with lane precedence.

- [ ] Add tests covering offline, usage stalled, banned, proxy unhealthy, direct route unhealthy, auth failure, and account suspension for all topology shapes.
- [ ] Run tests to capture failures.
- [ ] Apply common precedence without cross-lane mutation; preserve provider-specific banned policy.
- [ ] Run lifecycle suite; commit.

### Task 4: Expose accurate capacity and topology UI

**Files:**
- Modify: `app/main.py`
- Modify: `app/static/js/app.js`
- Test: `tests/test_deploy_modes_api.py`
- Test: `tests/test_frontend_wiring.py`

**Interfaces:** API/UI expose desired, deployable, running, free, blocked, capacity source, lane, expected/observed egress, and topology status.

- [x] Add failing API/UI assertions for missing-slot pending state and independent hybrid counts.
- [x] Implement response fields and warning copy without flattening lanes.
- [x] Run focused API/frontend tests; commit.

### Task 5: Complete fail-closed network verification

**Files:**
- Modify: existing provider runtime/network adapter files only where evidence identifies a defect.
- Create: `docs/evidence/provider-topology-network-audit-2026-09-13.md`

- [ ] Run read-only probes for direct IPv4, proxy IPv4, DNS, IPv6, UDP, DoH/DoT, and direct fallback on each lane.
- [ ] Fix only demonstrated contract violations; add regression tests first for each fix.
- [ ] Record commands, redacted outputs, and limitations.

### Task 6: Live canary matrix and production gate

**Files:**
- Create: `docs/evidence/provider-topology-live-canary-2026-09-13.md`
- Modify: `docs/evidence/provider-topology-production-readiness.md`

- [ ] Run authenticated, controlled direct-only, proxy-only, and hybrid canaries sequentially.
- [ ] Verify restart/reboot persistence, lease rotation CAS, release semantics, sticky ownership, and failure isolation.
- [ ] Audit UI through the authenticated browser: inputs, buttons, ready/partial/blocked states, and lane counts.
- [ ] Mark only individually evidenced gates as passing; keep the goal active for any missing evidence.

## Self-review

The plan covers cardinality, lease/release, ownership, lifecycle, UI/API, network security, and live verification. It intentionally does not add new provider abstractions or alter protected provider-specific runtimes without a failing regression test.
