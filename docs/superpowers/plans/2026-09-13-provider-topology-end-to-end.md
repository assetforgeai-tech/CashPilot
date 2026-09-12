# Provider Topology End-to-End Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make direct-only, proxy-only, and direct+proxy providers operationally consistent, isolated, and verifiable in production.

**Architecture:** Preserve the existing provider registry and slot planner. Add explicit lane semantics, independent capacity, lease ownership states, lane-scoped lifecycle, and fail-closed network evidence. Keep dedicated runtimes as adapters to the shared contract.

**Tech Stack:** Python, FastAPI/Pydantic, SQLite, Docker, pytest, Ruff.

## Global Constraints

- Direct-only uses only its assigned public IPv4 slot; no proxy fallback.
- Proxy-only uses only an eligible leased proxy egress; no direct fallback.
- Hybrid creates independent direct and proxy lanes; failure in one lane cannot stop the other.
- Deploy providers and nodes sequentially; isolate failures and continue the queue.
- `lease`, `runtime_release`, and `ownership_release` remain distinct operations.
- Account/provider ownership is released only by the existing explicit deletion policy.
- Existing scheduler behavior and user-created files remain untouched.

### Task 1: Lane contract and independent capacity

**Files:** `app/provider_runtime.py`, `app/provider_topology.py`, `app/main.py`; tests in `tests/test_provider_topology.py`, `tests/test_provider_topology_api.py`.

- Define lane contract fields: `topology`, `lane`, `slot_id`, `proxy_lease_id`, `expected_egress_ip`, `observed_egress_ip`.
- Calculate direct capacity from route-ready IPv4 slots and proxy capacity from scoped eligible proxies independently.
- Preserve hybrid desired count while reporting per-lane deployable/blocked/free counts.
- Add tests for direct-only, proxy-only, hybrid, and proxy shortage.

Progress: lane metadata (`lanes`, `capacity_basis`, `lane_isolation`) now flows through topology, catalog, deployment specs, and network reconciliation. Planner/API now consume direct IPv4 slots and proxy capacity independently: proxy-only workers can plan without public slots; hybrid lanes do not multiply capacities. Plan desired count includes existing non-retired proxy instances plus currently available proxy capacity, preserving idempotent reruns. Independent database capacity scoping remains provider-specific and live evidence is still required.

### Task 2: Lease ownership and lifecycle state machine

**Files:** `app/database.py`, `app/earnapp_recovery.py`, relevant lifecycle routes; tests for lease/release and ownership.

- Keep runtime lease release separate from sticky egress ownership release.
- Make lane identity part of lifecycle keys.
- Ensure proxy rotation affects only the proxy lane and uses CAS-safe replacement.
- Add tests proving an owned egress cannot be assigned to another account until explicit account deletion.

### Task 3: Unified lifecycle policy

**Files:** `app/provider_runtime.py`, `app/earnapp_lifecycle.py`, scheduler/reconciliation paths; lifecycle tests.

- Normalize actions by lane: offline/reported no-usage => restart; unhealthy proxy => rotate proxy; banned node => provider policy.
- Keep account suspended/locked distinct from node offline/banned.
- Ensure usage checks start at the earnings-update boundary and do not recreate identity implicitly.
- Add idempotence and failure-isolation tests.

### Task 4: Fail-closed network verification

**Files:** `app/provider_network_audit.py`, runtime network adapters, API response models; network tests.

- Verify expected and observed egress for every active lane.
- Require proxy lease evidence for proxy lanes.
- Detect direct fallback, IPv6/DNS/UDP leaks, missing sidecar/in-container enforcement, and untracked containers.
- Return `attention`/`unverified` rather than claiming healthy when evidence is absent.

### Task 5: UI/API reconciliation and capacity display

**Files:** provider plan endpoints and existing UI components; API/UI tests.

- Display topology, lane, slot/proxy assignment, expected vs observed egress, lease state, route state, and blocked reason.
- Show concise direct/proxy capacity counters per provider group.
- Keep hybrid lanes visually independent.
- Verify all controls and error states through existing browser test flow.

### Task 6: Live verification and release gate

**Files:** `docs/evidence/provider-topology-production-readiness.md`, runbooks.

- Verify one direct-only, one proxy-only, and one hybrid provider with sequential deploy, restart/reboot, rerun, lease rotation, and failure isolation.
- Reconcile NKN direct-IP mismatch before rerunning any slot; never rewrite leases blindly.
- Run focused tests, full suite, Ruff, compileall, and diff checks.
- Enable auto-deploy only after redacted live evidence proves every lane contract.

Progress: PR #314 merged; `v1.40.0` published; Compose pin PR #315 is open and requires normal approval. Proxy-only live evidence is recorded for `vps-test-us` (worker `1.33.3`, therefore network-shape evidence only); direct-only and hybrid evidence remain pending. Full local suite: `2926 passed, 8 skipped, 2 failed`; both failures are the known Compose-pin mismatch (`1.39` versus repository-visible newest release `1.35`) and are not caused by this change. Network inventory now exposes fail-closed `network_evidence` findings for missing DNS/IPv6/UDP proof.
