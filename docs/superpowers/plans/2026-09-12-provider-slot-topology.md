# Provider Slot Topology Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every deployable provider converge deterministically from the worker's ready public-IPv4 slots for direct-only, direct-and-proxy, and proxy-only topologies.

**Architecture:** Add a pure topology planner between provider capabilities and deployment. Preserve dedicated NKN and EarnApp orchestrators; generic providers receive deterministic per-worker/per-mode/per-slot instance IDs, direct slot network contracts, and exclusive proxy leases. Reconciliation remains sequential and records each failure without blocking later nodes or providers.

**Tech Stack:** Python, FastAPI, SQLite, Docker worker API, pytest.

## Global Constraints

- Ready bootstrap-owned IPv4 slots are authoritative for desired node count.
- Provider execution is sequential; node execution inside each provider is sequential.
- A failed provider or node never blocks later work.
- Auto deploy stays disabled until dry-run and live canary verification pass.
- NKN and EarnApp keep their dedicated planners and lifecycle contracts.
- No node may silently fall back from proxy egress to the worker's direct IP.
- Existing live nodes are not deleted, rotated, or recreated during planner rollout.

---

### Task 1: Pure topology planner

Implementation status: planner and focused contract tests landed in the provider topology rollout PR.

**Files:**
- Create: `app/provider_topology.py`
- Test: `tests/test_provider_topology.py`

**Interfaces:**
- Consumes: `provider_runtime.ProviderRuntime`, worker id, ready slot records.
- Produces: `plan_provider_nodes(worker_id, slug, slots, mode=None)` and immutable node plans.

- [ ] Write failing tests for all three topology classes, deterministic IDs, non-ready slots, duplicates, and mode filtering.
- [ ] Run `pytest tests/test_provider_topology.py -q` and confirm failure because the module is absent.
- [ ] Implement the smallest pure planner satisfying the tests.
- [ ] Re-run the focused test and confirm it passes.

### Task 2: Slot-aware generic deployment

**Files:**
- Modify: `app/main.py`
- Modify: `app/worker_api.py`
- Test: `tests/test_deploy_modes_api.py`
- Test: `tests/test_provider_slot_deploy.py`

**Interfaces:**
- Consumes: topology plans and `/api/network/slots` records.
- Produces: sequential per-slot deployment with durable slot metadata.

- [ ] Write failing tests proving one node per ready slot and both lanes for direct-and-proxy providers.
- [ ] Add deterministic instance naming and slot labels/spec metadata.
- [ ] Pass the selected direct slot network contract to the worker.
- [ ] Lease one distinct eligible proxy per proxy plan and fail that node closed when capacity is unavailable.
- [ ] Persist failures per instance, continue with later plans, return desired/running/pending/failed counts.
- [ ] Run focused deployment tests.

### Task 3: Reconciliation and auto-deploy safety

**Files:**
- Modify: `app/main.py`
- Modify: `app/database.py`
- Test: `tests/test_auto_deploy_policy.py`
- Test: `tests/test_provider_slot_reconcile.py`

**Interfaces:**
- Consumes: desired plans plus recorded provider instances.
- Produces: idempotent missing-node reconciliation without mutating healthy matching instances.

- [ ] Write failing tests for idempotency, retry of failed nodes, provider failure isolation, and node failure isolation.
- [ ] Implement reconciliation and dry-run response.
- [ ] Keep dedicated NKN/EarnApp ordering and add generic slot reconciliation between them.
- [ ] Run focused reconciliation tests.

### Task 4: Capacity and dashboard truth

**Files:**
- Modify: `app/main.py`
- Modify: `app/static/js/app.js`
- Modify: dashboard template/styles selected by existing UI structure.
- Test: relevant API/UI tests.

**Interfaces:**
- Produces per-provider desired, running, pending proxy, blocked input, and failed counts.

- [ ] Add API contract tests for capacity summaries.
- [ ] Implement concise topology/capacity output.
- [ ] Render direct and proxy lanes separately without exposing credentials.
- [ ] Verify responsive and empty/error states.

### Task 5: Provider exceptions and readiness gates

**Files:**
- Modify: `app/provider_runtime.py`
- Modify: catalog/runtime tests.

**Interfaces:**
- Produces explicit slot policy: dedicated, per-slot, single-worker, or manual-only.

- [ ] Encode NKN and EarnApp as dedicated planners.
- [ ] Gate Mysterium multi-slot deployment until wallet/TUN/port independence is proven.
- [ ] Gate count-only/manual-only providers lacking deploy evidence.
- [ ] Test every active provider has an explicit topology policy.

### Task 6: Verification and controlled rollout

**Files:**
- Create/update redacted evidence under `docs/evidence/`.

- [ ] Run focused tests, full pytest, compileall, lint, and security checks.
- [ ] Inspect dry-run plans for Azure workers `112444` and `112494`; require ten ready unique slots each.
- [ ] Validate credentials/accounts/wallets and eligible proxy capacity without exposing secrets.
- [ ] Canary one provider from each topology class sequentially.
- [ ] Verify instance identity, direct egress binding, proxy fail-closed behavior, unique egress, heartbeat, reboot persistence, and failure continuation.
- [ ] Enable scoped auto-deploy only after all gates pass, then reconcile both Azure workers.
- [ ] Recheck dashboard truth against worker containers and durable leases.
