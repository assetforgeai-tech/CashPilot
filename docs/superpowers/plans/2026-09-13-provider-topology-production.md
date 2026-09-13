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

- [ ] Add tests proving every provider lane defaults to detected public IPv4 cardinality, while eligible proxy count gates proxy deployment and explicit desired counts remain targets with pending capacity.
- [ ] Keep planner defaults and summaries so direct readiness uses IPv4 routes while proxy readiness uses eligible proxies without shrinking desired topology.
- [ ] Preserve blocked/partial/ready status and no cross-lane fallback.
- [ ] Run focused topology tests.

### Task 2: Provider contract metadata

**Files:** `app/provider_runtime.py`, tests covering catalog/runtime

- [ ] Add explicit auth scope, account sharing, ownership policy, heartbeat interval/timeout, and network contract metadata.
- [ ] Expose these fields through `catalog_runtime` and topology contracts.
- [ ] Add validation tests for all provider classes.

### Task 3: Lease and ownership policy

**Files:** `app/database.py`, `app/routers/proxies.py`, tests for proxy leases

- [ ] Preserve runtime lease CAS behavior.
- [ ] Enforce provider ownership policy for sticky providers; release ownership only on account/provider retirement.
- [ ] Ensure rotation releases only the old runtime lease and never violates sticky egress ownership.
- [ ] Add tests for release, rotate, account deletion, duplicate egress, and cross-provider behavior.

### Task 4: Lifecycle state machine

**Files:** `app/provider_lifecycle.py`, scheduler/reconciliation callers, lifecycle tests

- [ ] Normalize precedence: auth failure observe; direct route failure blocked; proxy failure rotate; offline restart; usage stall restart; provider-specific recreate only when declared.
- [ ] Add explicit heartbeat interval, timeout, confirmation count, and action metadata.
- [ ] Keep missing inventory two-confirmation cleanup and cancel cleanup on reappearance.
- [ ] Add tests for direct-only, proxy-only, and hybrid lanes.

### Task 5: Network contract

**Files:** `app/singbox_config.py`, runtime/network builders, proxy tests

- [ ] Make `egress_mode`, `fallback=none`, DNS tunnel, IPv6 policy, UDP policy, and fail-closed behavior explicit for every lane.
- [ ] Reject invalid fallback or incompatible backend/provider combinations at API validation.
- [ ] Add config and regression tests for DNS, IPv6, UDP, and direct-fallback prevention.

### Task 6: API and dashboard

**Files:** API routers/models, `app/static/js/app.js`, frontend tests

- [ ] Reject unsupported lane requests and missing route/proxy capacity with actionable reasons.
- [ ] Render direct/proxy lane totals, running/free/blocked counts, capacity source, and topology status without flattening hybrid state.
- [ ] Add UI tests for ready/partial/blocked and all three provider classes.

### Task 7: Verification and live evidence

- [ ] Run full tests, Ruff, format, diff checks, and security checks.
- [ ] Redeploy after release gates pass; canary one proxy-only and one hybrid direct/proxy lane before scaling.
- [ ] Verify lease uniqueness, rotation/release, restart/reboot persistence, DNS/IPv6/UDP fail-closed behavior, and two-confirmation cleanup.
- [ ] Capture evidence in `docs/evidence/provider-topology-live-2026-09-13.md` and final readiness report.
