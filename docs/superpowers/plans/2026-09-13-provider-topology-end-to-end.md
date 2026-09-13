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

Progress: lane metadata (`lanes`, `capacity_basis`, `lane_isolation`) now flows through topology, catalog, deployment specs, and network reconciliation. Planner/API now consume direct IPv4 slots and proxy capacity independently: proxy-only workers can plan without public slots; hybrid lanes do not multiply capacities. Plan desired count includes existing non-retired proxy instances plus currently available proxy capacity, preserving idempotent reruns; summaries expose available proxy capacity separately. Runtime matrix declares `egress_ownership_scope`: EarnApp is `account_sticky`; other providers remain `runtime_lease`. Hybrid callers can now submit explicit `direct_desired` and `proxy_desired` targets; omitted targets retain all-available behavior, while over-capacity targets are returned as blocked/pending rather than silently reduced. Live evidence is still required.

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

Progress: shared lifecycle dispatcher now accepts `usage_stalled`; it restarts
the same lane, while an unhealthy proxy still takes precedence and rotates.
Existing EarnApp account authentication remains a separate `defer_auth` path.

Progress: proxy-only deployment now fails closed when the provider capacity query
proves zero eligible proxies; it returns `pending_capacity` and never falls back
to a direct or legacy deployment.

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
Progress: PR #314 merged; `v1.40.0` published; Compose examples now pin `1.40` and the full local suite is `2947 passed, 8 skipped`. PR #316 checks are all green and merge state is `CLEAN`, but normal required approval remains outstanding. Proxy-only live evidence is recorded for `vps-test-us` (worker `1.33.3`, therefore network-shape evidence only); direct-only and hybrid evidence remain pending. Network inventory now exposes fail-closed `network_evidence` findings for missing DNS/IPv6/UDP proof. Read-only follow-up on iOS/macOS confirmed distinct egress, loopback DNS, redsocks, and explicit IPv4/IPv6 terminal-drop chains; UDP behavior and direct/hybrid live proof remain unverified.

### Task 7: Fail closed on unknown proxy capacity

**Files:** `app/provider_topology.py`; tests in `tests/test_provider_topology.py`.

- Treat `proxy_capacity=None` as discovery pending, never as an IPv4-shaped proxy target.
- Preserve explicit `proxy_capacity=0` as zero capacity and return blocked proxy plans.
- Keep direct and hybrid planning unchanged.
- [x] Add regression tests for unknown capacity and explicit zero capacity.
- [x] Run `pytest tests/test_provider_topology.py -q`.

Progress: implemented and pushed in `4afe4ab`; explicit deploy-capacity test coverage followed in `1f34d93`. Focused topology/API verification: `37 passed`.

### Task 8: Slot-based direct-only contract

**Files:** `app/provider_runtime.py`, `app/provider_topology.py`, `app/main.py`; tests in `tests/test_provider_topology_api.py`.

- Mark direct-only providers that are provisioned per public IPv4 as `slot_direct`.
- Keep genuinely dedicated/manual providers on their dedicated adapters.
- Expose `public_ipv4_slot`, expected egress, and route state in API payloads.
- [x] Add API tests proving direct-only count equals route-ready slots and never proxy capacity.

Progress: Azure live preflight confirms both workers expose 10/10 route-ready
IPv4 slot manifests with dedicated Docker network metadata. NKN/Mysterium remain
dedicated adapters by design; generic slot planner is not used for their wallet
and host-agent lifecycle.

### Task 9: Lane-scoped counters and reconciliation UI

**Files:** existing provider catalog/API/UI components; tests in `tests/test_deploy_modes_api.py` and UI tests.

- Render direct/proxy counters separately: desired, running, free, blocked, pending.
- Show proxy `eligible`, `leased`, `owned`, `available`, and duplicate egress counts.
- Show lane, capacity source, expected/observed egress, lease and ownership state per node.
- [ ] Exercise every control and empty/error state through the existing browser test flow.

Progress: deploy status now renders per-lane running/desired/free/pending values
from the API response (`83f6167`). Lease/ownership/expected-vs-observed egress
remains a separate reconciliation view and still requires browser verification. Hybrid deploy forms now expose optional independent direct/proxy targets and include them in deploy requests; browser verification remains pending.

Progress: generic provider runtime reconciliation now uses the same two-confirmed-
inventory safety rule as the EarnApp path, excluding EarnApp so sticky ownership
cannot be released by the generic cleanup path.

### Task 10: End-to-end live gates

**Files:** `docs/evidence/provider-topology-production-readiness.md`, runbook evidence.

- Capture direct-only, proxy-only, and hybrid evidence using the current released worker.
- Verify sequential deployment, restart/reboot persistence, proxy rotation, lease/release, orphan reconciliation, and provider failure isolation.
- Run DNS, IPv6, UDP, DoH/DoT, and direct-fallback probes for every lane.
- [ ] Do not mark production-ready until every gate has redacted evidence.
