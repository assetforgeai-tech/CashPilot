# Provider Topology Production Implementation Plan

**Goal:** Make direct-only, proxy-only, and hybrid providers production-ready with explicit capacity, isolated lanes, durable ownership, consistent lifecycle policy, safe networking, and operator-visible state.

**Architecture:** Keep provider truth in `app/provider_runtime.py`; keep pure planning in `app/provider_topology.py`; keep state transitions in `app/provider_lifecycle.py`; keep lease ownership in database/API routes; expose the same contract through API and UI. Provider-specific runtimes remain adapters and never receive implicit cross-lane fallback.

**Tech Stack:** Python, FastAPI, SQLite, Docker, vanilla dashboard JavaScript, pytest, Ruff.

## Global Constraints

- Direct-only uses ready public IPv4 slots and never falls back to proxy.
- Proxy-only cardinality follows detected public IPv4 slots; eligible proxy capacity gates deployment and never falls back to direct.
- Hybrid plans independent direct/proxy lanes and never crosses lanes.
- EarnApp sticky egress ownership survives runtime lease release until account deletion.
- Runtime failures fail closed; no direct network fallback from proxy lanes.
- Existing user artifacts and unrelated provider containers remain untouched.

### Task 1: Capacity planning

**Files:** `app/provider_topology.py`, `tests/test_provider_topology.py`

- [x] Add tests proving every slot-based provider lane defaults to detected public IPv4 cardinality, while eligible proxy count gates proxy deployment and explicit desired counts remain targets with pending capacity.
- [x] Keep planner defaults and summaries so direct readiness uses IPv4 routes while proxy readiness uses eligible proxies without shrinking desired topology.
- [x] Preserve blocked/partial/ready status and no cross-lane fallback.
- [x] Bind every proxy lane to a durable capacity slot and retain its source public-IPv4 slot for reconciliation.
- [x] Run focused topology tests.

### Task 2: Provider contract metadata

**Files:** `app/provider_runtime.py`, tests covering catalog/runtime

- [x] Add explicit auth scope, account sharing, ownership policy, heartbeat interval/timeout, and network contract metadata.
- [x] Expose these fields through `catalog_runtime` and topology contracts.
- [x] Add validation tests for all provider classes.

### Task 3: Lease and ownership policy

**Files:** `app/database.py`, `app/routers/proxies.py`, tests for proxy leases

- [x] Preserve runtime lease CAS behavior.
- [x] Enforce provider ownership policy for sticky providers; release ownership only on account/provider retirement.
- [x] Ensure rotation releases only the old runtime lease and never violates sticky egress ownership.
- [x] Add tests for release, rotate, account deletion, duplicate egress, and cross-provider behavior.

### Task 4: Lifecycle state machine

**Files:** `app/provider_lifecycle.py`, scheduler/reconciliation callers, lifecycle tests

- [x] Normalize precedence: auth failure observe; direct route failure blocked; verified proxy failure rotate. Offline, usage-stalled, and banned-node recovery is EarnApp-only; other providers observe unless their dedicated adapter declares a separate policy.
- [x] Keep Pawns/IPRoyal allocation provider-private; `ip_used` masks and replaces only inside its provider scope.
- [x] Add explicit heartbeat interval, timeout, confirmation count, and action metadata.
- [x] Keep missing inventory two-confirmation cleanup and cancel cleanup on reappearance.
- [x] Add tests for direct-only, proxy-only, and hybrid lanes.

### Task 5: Network contract

**Files:** `app/singbox_config.py`, runtime/network builders, proxy tests

- [x] Make `egress_mode`, `fallback=none`, DNS tunnel, IPv6 policy, UDP policy, and fail-closed behavior explicit for every lane.
- [x] Reject invalid fallback or incompatible backend/provider combinations at API validation.
- [x] Add config and regression tests for DNS, IPv6, UDP, and direct-fallback prevention.

### Task 6: API and dashboard

**Files:** API routers/models, `app/static/js/app.js`, frontend tests

- [x] Reject unsupported lane requests and missing route/proxy capacity with actionable reasons.
- [x] Render direct/proxy lane totals, running/free/blocked counts, capacity source, and topology status without flattening hybrid state.
- [x] Add UI tests for ready/partial/blocked and all three provider classes.
- [x] Separate provider detail into accessible Input, Runtime, and Collector tabs without adding new routes.

### Task 7: Verification and live evidence

- [x] Run full tests, Ruff, format, diff checks, and source security audit. Full suite retains two known Compose release-ref fixture failures.
- [ ] Redeploy after release gates pass; canary one proxy-only and one hybrid direct/proxy lane before scaling.
- [x] Perform read-only live-worker preflight without Azure CLI; record current container/NAT evidence.
- [ ] Verify lease uniqueness, rotation/release, restart/reboot persistence, DNS/IPv6/UDP fail-closed behavior, and two-confirmation cleanup on live workers.
- [ ] Capture evidence in `docs/evidence/provider-topology-live-2026-09-13.md` and final readiness report.
