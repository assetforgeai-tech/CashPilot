# Proxy Route and Proxy Pool Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` task-by-task. This addendum supersedes the proxy-runtime and proxy-recheck portions of `docs/superpowers/plans/2026-09-21-production-operations-parallelization.md`.

**Date:** 2026-09-23

**Goal:** Standardize fail-closed fake-proxy behavior and redesign Proxy Pool recheck/rotation so a dead upstream is handled promptly and safely from one source of truth, without breaking provider-specific allocation, identity, wallet, account, or heartbeat policies.

**Architecture:** Proxy Pool Probe is the only authority that decides whether an upstream proxy is `alive`, `suspect`, or `dead`. The worker-side route wrapper/watchdog is a local safety mechanism: it prevents direct fallback and stops the provider process when the local route cannot be trusted. A durable server-side rotation queue consumes dead-proxy transitions and applies one CAS-guarded replacement at a time. ACK and observed egress remain commit gates, not independent proxy-death authorities.

**Tech Stack:** Python/FastAPI, SQLite transactions, asyncio bounded queues, Docker restart policies, `redsocks`/iptables or the declared sidecar backend, sing-box with immutable image digest, pytest, Ruff, packet-level canary evidence.

## Global Constraints

- Work only from a fresh worktree based on `origin/main`; preserve the dirty CP-013 evidence worktree.
- No production, `test-sing`, `test-us`, `sing`, or `eapp` mutation during CP-015A–F.
- Do not rotate, delete, release, or reassign a real proxy solely from a watchdog event or one failed probe.
- Proxy Pool Probe remains the sole upstream-liveness authority; provider-specific allocators remain isolated.
- EarnApp account/link/recovery policy and Pawns/IPRoyal `ip_used` policy are not generalized.
- Direct-only Mysterium/NKN never receive proxy leases or fake-proxy wrappers.
- No secret, token, cookie, password, wallet, database, or raw provider response enters Git, logs, or evidence.
- Every implementation task writes focused tests first, records secret-free evidence, and runs the repository quality gates before handoff.
- Runtime route health TTL is not lease ownership TTL. TTL expiry can fail-closed and request recheck; it cannot release ownership.
- No new third-party dependency is added for queues, retries, or state machines; use existing Python/SQLite/asyncio/Docker facilities.

## Why the watchdog remains required

The watchdog and Proxy Pool solve different failures:

| Layer | Detects | Allowed action | Must not do |
|---|---|---|---|
| Proxy Pool Probe | Upstream proxy endpoint/protocol/egress failure | Persist transition; enqueue rotation | Decide provider identity, delete a node, or contact a worker directly |
| Route watchdog | Local `redsocks`/DNS/iptables/sidecar route failure | Fail closed; stop provider process so Docker can restart the same container | Mark the upstream proxy dead or release its lease |
| Worker heartbeat | VPS/control-plane liveness | Mark worker offline; later reclaim all worker-bound runtime resources | Infer proxy health |
| ACK + observed egress | Candidate apply and runtime/DB agreement | Allow CAS commit or rollback | Replace Proxy Pool liveness |

Current behavior is incomplete. The EarnApp wrapper can terminate its provider
when a route helper/firewall rule disappears. `app/proxy_runtime.py` renders an
equivalent script, but the shared-proxy `app/orchestrator.py` path currently
uses a sing-box sidecar instead; a code grep finds no production call to
`render_entrypoint()`. Its sidecar retries `sing-box run` in a loop while the
provider container can stay alive. Docker creates new managed provider and
sidecar containers with `restart_policy={"Name": "always"}`. A process exit
restarts the same container, not a re-deploy, so its mounted identity volumes
should remain attached; verify this on a disposable canary and inspect old
containers before relying on their historical Docker restart policy.

## Operational risks and required controls

Stopping the provider is the safe action when routing cannot be proven. It still has risks that must be controlled before rollout:

1. **Crash loop:** a broken local route can repeatedly start and stop a provider. Add startup grace and expose restart-count/backoff evidence. If restarts keep failing, the provider remains unable to send direct traffic, displays `route_blocked`, and raises an alert. Docker `restart: always` does not itself enforce a maximum retry count; do not claim a hard stop until a separate, tested supervision rule actually enforces one. Do not recreate the provider identity automatically.
2. **False positive during bootstrap:** the watchdog must not kill a provider before redsocks/DNS/sidecar startup grace completes. Route readiness must be explicit.
3. **Sidecar/provider race:** a separately restarting sidecar can leave a provider process alive with no trusted route. The watchdog must observe the sidecar route contract, not only the provider PID.
4. **Intentional stop ambiguity:** `always` is suitable for unattended runtime but can surprise an operator after daemon/host restart. Verify the actual stop/restart semantics in the disposable runbook; do not add a new administrative-stop marker unless existing controls cannot express it.
5. **Identity loss on the wrong action:** `docker restart` preserves the container and volumes; `docker rm` followed by catalog redeploy can attach a different volume and create a new provider identity. Watchdog recovery may restart only. Recreate is a separate, approved provider policy action.
6. **Provider penalties:** a hot loop can look like repeated reconnects or churn. After the alert threshold is reached, suppress provider traffic through fail-closed routing and escalate for controlled recovery. Never infer that the upstream proxy is dead from the local watchdog.

## Network contract to adopt

Adopt the EarnApp safety invariants, not a blind copy of EarnApp account/runtime code:

- no direct fallback for a proxy lane;
- all provider TCP traffic uses the declared route backend;
- DNS is forced through the declared proxy-owned DNS/DoH path;
- IPv6 is blocked or explicitly tunneled according to the provider matrix;
- UDP is explicitly allowed only when the provider/proxy contract says so;
- only the pinned upstream proxy endpoint is allowed by the egress firewall;
- startup requires route readiness and expected egress verification;
- route failure stops the provider and leaves the runtime fail-closed;
- route evidence contains no secret, token, cookie, or wallet material;
- the sidecar image is pinned by digest, never `latest`.

Backend adapters remain explicit:

- EarnApp: retain its dedicated in-container/reference runtime and account policy.
- Shared proxy providers: use the common fail-closed route contract with the declared `singbox_compat` or `redsocks` backend; do not force an incompatible binary path.
- Pawns/IPRoyal: keep the provider-private allocator, `ip_used`, mask-and-replace, and admission/rotation decisions; only the route safety contract is shared.
- Mysterium/NKN direct-only: no fake-proxy route and no proxy lease.

The contract is not considered standardized until packet evidence proves TCP, DNS/DoH, IPv6, UDP, direct-fallback, egress, watchdog, and reboot behavior for each applicable provider group.

### Runtime route-health TTL

The route wrapper needs a freshness bound separate from proxy ownership. The
canary default is an active route probe every 30 seconds, a 90-second route
health TTL, and three consecutive failed route probes before `route_blocked`.
These values are server-configured, bounded, and recorded in evidence; they do
not expire or release a `provider_proxy_leases` row. When the TTL expires, the
worker fails closed and emits a recheck request. Only a Proxy Pool transition
to `dead` can enqueue upstream rotation.

## Proxy Pool state and rotation design

### Durable state

Keep `proxy_probe_results` as append-only evidence. Add a compact current-state table and an idempotent rotation-request table instead of overloading the existing `proxy_endpoints.status` field:

```sql
CREATE TABLE IF NOT EXISTS proxy_probe_state (
    proxy_id INTEGER PRIMARY KEY,
    state TEXT NOT NULL CHECK(state IN ('unknown','alive','suspect','dead','quarantined')),
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    consecutive_successes INTEGER NOT NULL DEFAULT 0,
    last_probe_at TEXT,
    next_probe_at TEXT,
    last_transition_at TEXT,
    last_failure_reason TEXT NOT NULL DEFAULT '',
    probe_generation INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(proxy_id) REFERENCES proxy_endpoints(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS proxy_rotation_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proxy_id INTEGER NOT NULL,
    probe_generation INTEGER NOT NULL,
    provider_slug TEXT NOT NULL,
    worker_id INTEGER NOT NULL,
    instance_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','running','succeeded','failed','cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TEXT NOT NULL DEFAULT (datetime('now')),
    lease_token TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(proxy_id, probe_generation, provider_slug, worker_id, instance_id),
    FOREIGN KEY(proxy_id) REFERENCES proxy_endpoints(id) ON DELETE CASCADE,
    FOREIGN KEY(worker_id) REFERENCES workers(id) ON DELETE CASCADE
);
```

The schema is the minimal target shape, not a command to apply on production.
Migration tests must preserve existing rows and indexes, use one short SQLite
transaction per transition, and separately model legacy worker-level
assignments and provider-instance leases. An in-use dead proxy stays reserved
until replacement CAS succeeds; it must not become available to a second
consumer during rotation. Existing Pawns allocator decisions remain outside
this generic admission path.

Probe grouping must use the exact endpoint, port, protocol, and a protected
credential identity. Existing `app/proxy_health.py:probe_key()` groups by
egress IP first; distinct endpoints that happen to share an exit IP must not
be considered the same physical health check. Do not expose credentials in a
group key, log, or evidence.

### State transitions

Use these defaults unless a provider adapter declares a stricter threshold:

```text
unknown → alive              successful probe
alive   → suspect            first failed probe
suspect → alive              successful probe
suspect → dead               configured consecutive-failure threshold (default 3)
dead    → rotation_pending   active lease exists
dead    → quarantined        no safe replacement or provider policy blocks reuse
dead    → alive              successful recovery before rotation commit
```

Three retries inside one probe attempt do not count as three independent
health cycles. A successful probe resets the failure counter. Timeout from a
control-plane outage, DNS outage, or shared probe target is `inconclusive`,
not proven upstream death; it cannot increment the upstream failure counter.
Do not erase the last confirmed egress IP merely because one check failed.
An egress change invalidates the old binding until ownership and sticky-account
policy approve it. A single transient failure never rotates a lease.

### Event-driven recheck and rotation

The scanner must not wait for a 50k-proxy sweep before acting:

```text
incremental scanner
  → bounded probe queue
  → probe worker
  → transactional state transition
  → append probe evidence
  → enqueue one deduplicated rotation request when threshold is reached
  → rotation worker claims request with CAS
  → provider adapter selects replacement
  → worker apply ACK + observed egress
  → lease CAS commit
  → finalize binding and evidence
```

The rotation request is emitted after the individual proxy transition is committed, not by a direct callback from the probe coroutine. This makes retries, process restarts, and duplicate events safe.

The existing `run_proxy_pool_recheck()` rotates only rows with
`assigned_worker_id`; the new query must find all affected active provider
instance leases as well as legacy worker-level assignments. Before enqueueing,
compare assignment generation and account/provider ownership. Pawns-specific
allocator and EarnApp account recovery stay in their own adapters.

Rotation rules:

- one request per active lease/assignment generation and probe generation;
- serialize rotations per worker and per provider instance;
- keep the old lease until candidate apply, ACK, observed egress, and CAS commit succeed;
- on failure, keep the old binding/lease, increment request attempts, and retry with backoff;
- no direct fallback unless an explicit provider contract permits it;
- no proxy delete or release solely because of one probe failure;
- provider-specific adapters retain EarnApp account rules and Pawns `ip_used` rules;
- generic liveness cannot mark a provider-specific capability (for example EarnApp WSS or EarnFM socket qualification) as healthy; profile results remain independent.

## Scale design for 50,000 proxies

Replace `asyncio.gather()` over the whole target list with:

- paged DB reads, default page size 500;
- a bounded probe queue, default capacity 1,024;
- a fixed probe worker pool bounded by the existing configured concurrency;
- a separate bounded rotation queue;
- leased proxies first, then stale idle proxies by `next_probe_at`;
- persisted `next_probe_at` scheduling so a restart resumes without rebuilding 50,000 tasks;
- recovery of `running` probe/rotation work to `pending` after a control-plane restart;
- per-proxy timeout, exponential backoff, jitter, and provider/network circuit breaker;
- metrics for queue depth, probe latency, dead-to-rotation latency, rotation success/failure, stale work, and flapping.

The scheduler keeps the existing UI auto-recheck setting and its 15-minute
trigger. The displayed 60-minute interval / 32 parallel checks is a screenshot,
not proof that those settings were saved to the control-plane DB. The tick must
not start a second full scan while one is active. Keep manual recheck (which
*writes probe results* but has `rotate_dead=false` in the UI) independent from
scheduled rotation. Define separate configurable probe intervals for leased
and idle proxies only if the operator accepts different freshness guarantees.
Budget the effective scan interval as `total_due * observed_p95_probe_seconds /
effective_concurrency`; if it exceeds the requested interval, show backlog and
mark freshness `unknown` instead of promising timely rotation. Full scale may
require multiple prober workers after the single-process benchmark; do not
assume 50,000 proxies can be covered in an hour at concurrency 32.

The current scheduler also serializes generic, EarnApp WSS, and EarnFM socket
qualification passes. Preserve profile separation and schedule provider
qualification only for eligible/due proxies so a slow generic sweep cannot
silently delay every provider-specific result.

## Implementation tasks and ownership

CP-015A–F below are *proposed* IDs, not existing Beads records. Create and link
them in the verified shared Beads store only after the plan is accepted and
merged; do not invent completion or mutate the isolated worktree's Beads DB.
They gate continued CP-013 production rollout; closed CP-011/012 remain closed.
They may not mutate live production resources.

### CP-015A: Freeze proxy route and state-machine contracts

**Depends on:** CP-003, CP-004, CP-009.

**Files:**
- Create: `docs/architecture/proxy-route-contract.md`
- Create: `docs/architecture/proxy-pool-state-machine.md`
- Modify: `docs/architecture/provider-policy-matrix.md`
- Test: `tests/test_proxy_route_contract.py`
- Evidence: `docs/evidence/CP-015A-YYYY-MM-DD.md`

**Acceptance:** provider classes, backend adapters, watchdog boundaries, state transitions, retry thresholds, fallback rules, and ACK/egress commit gates are machine-checked; Pawns and EarnApp lanes remain separate.

- [ ] Add failing contract tests for direct-only, hybrid, proxy-only, watchdog, TTL, and fallback invariants.
- [ ] Record the exact state-transition table and canary defaults in the two architecture documents.
- [ ] Run `python -m pytest -q tests/test_proxy_route_contract.py` and confirm the new tests pass.
- [ ] Run `git diff --check` and write `docs/evidence/CP-015A-YYYY-MM-DD.md`.

### CP-015B: Durable probe state and rotation-request authority

**Depends on:** CP-009 and CP-015A.

**Files:**
- Modify: `app/database.py` only for the two migrations and their transaction helpers
- Create: `app/proxy_pool_state.py`
- Test: `tests/test_proxy_pool_state.py`
- Evidence: `docs/evidence/CP-015B-YYYY-MM-DD.md`

**Interfaces:**
- `record_proxy_probe_transition(proxy_id, result, *, generation) -> dict`
- `enqueue_proxy_rotation_requests(proxy_id, probe_generation) -> int`
- `claim_proxy_rotation_request(now) -> dict | None`
- `complete_proxy_rotation_request(request_id, state, *, error='') -> None`

**Acceptance:** transitions are idempotent; old leases are preserved until CAS replacement; duplicate probe generations create no duplicate request; restart recovery returns abandoned work to `pending`.

- [ ] Add RED tests for first failure, threshold failure, recovery, duplicate generation, and abandoned request recovery.
- [ ] Add the two SQLite migrations and transaction helpers without changing existing lease ownership semantics.
- [ ] Run `python -m pytest -q tests/test_proxy_pool_state.py`.
- [ ] Run `uv run ruff check .`, `uv run ruff format --check .`, `python -m compileall -q app tests`, and `git diff --check`.

### CP-015C: Incremental probe scheduler and immediate rotation queue

**Depends on:** CP-015B.

**Files:**
- Modify: `app/routers/proxies.py` only in recheck/probe orchestration
- Modify: `app/main.py` only in `_run_proxy_pool_recheck_scheduler`
- Create: `app/proxy_pool_scheduler.py`
- Test: `tests/test_proxy_pool_scheduler.py`, `tests/test_proxy_pool_rotation_queue.py`
- Evidence: `docs/evidence/CP-015C-YYYY-MM-DD.md`

**Acceptance:** a dead leased proxy enqueues rotation before the rest of the pool finishes; whole-pool memory is bounded; scheduler does not overlap scans; `rotate_dead=false` remains a read-only/manual mode; automatic scheduler uses the durable queue.

- [ ] Add RED tests proving a completed dead probe enqueues before a slow unrelated probe completes.
- [ ] Replace whole-list `asyncio.gather()` with paged reads and bounded queues; retain the existing manual endpoint behavior.
- [ ] Add restart recovery, timeout, backoff, deduplication, and 50,000-row synthetic-load tests.
- [ ] Run `python -m pytest -q tests/test_proxy_pool_scheduler.py tests/test_proxy_pool_rotation_queue.py`.

### CP-015D: Shared fail-closed route and watchdog hardening

**Depends on:** CP-004, CP-014G, CP-014H, CP-015A.

**Files:**
- Modify: `app/proxy_runtime.py`
- Modify: `app/earnapp_runtime.py` only for equivalent watchdog controls
- Modify: `app/orchestrator.py` only for sidecar digest pin, route readiness, restart/backoff labels, and health contract
- Test: `tests/test_proxy_runtime.py`, `tests/test_orchestrator_proxy_route.py`, `tests/test_watchdog_restart_contract.py`
- Evidence: `docs/evidence/CP-015D-YYYY-MM-DD.md`

**Required behavior:** startup grace; route-ready marker; provider termination on trusted-route loss; bounded restart evidence; no identity recreation; sidecar/provider dependency ordering; IPv6/DNS/direct-fallback fail-closed checks; immutable sing-box reference instead of `ghcr.io/sagernet/sing-box:latest`.

**Acceptance:** fault-injecting a helper causes provider stop and container restart without changing identity/volume; repeated failures enter `route_blocked` with evidence; recovery requires route readiness; direct traffic is impossible during helper failure.

- [ ] Add RED tests for startup grace, helper death, firewall-chain loss, sidecar restart, TTL expiry, restart budget, and identity/volume preservation.
- [ ] Implement the smallest wrapper/orchestrator changes; do not change provider account or allocator code.
- [ ] Replace the sidecar `latest` reference with the release manifest's immutable digest.
- [ ] Run `python -m pytest -q tests/test_proxy_runtime.py tests/test_orchestrator_proxy_route.py tests/test_watchdog_restart_contract.py`.

### CP-015E: New disposable scale and provider-group canary

**Depends on:** CP-015A through CP-015D and a fresh disposable-resource approval. This is a new follow-up canary; do not reopen or mutate the already closed CP-011 resources.

**Resources:** disposable canary only; no `test-sing`, `test-us`, `sing`, `eapp`, or production.

**Checks:** 50k synthetic proxy state load; bounded queue memory; dead-proxy event latency; duplicate-event replay; worker restart; control-plane restart; watchdog fault injection; packet capture; EarnApp lane; Pawns private allocator lane; one shared-proxy provider group; direct-only negative control.

**Acceptance:** machine-readable evidence shows no direct fallback, no lease duplication, no queue loss, no identity reset, and rotation begins before full scan completion.

- [ ] Generate synthetic 50,000-row pool data without real credentials or provider responses.
- [ ] Fault-inject route helpers and replay duplicate probe/rotation events.
- [ ] Capture packet-level TCP, DNS/DoH, IPv6, UDP, and direct-fallback evidence for each selected provider group.
- [ ] Verify restart/reboot persistence, identity/volume hashes, queue recovery, and rollback; clean only disposable resources.

### CP-015F: New release gate for CP-013

**Depends on:** CP-015E and all required CP-014 reliability/port gates.

**Files:**
- Modify: `docs/superpowers/plans/2026-09-21-production-operations-parallelization.md` only to link this addendum and update dependency order
- Create: `docs/evidence/CP-015F-YYYY-MM-DD.md`

**Acceptance:** CP-015E is PASS; a new release candidate contains the route/pool changes and rollback manifest; historical CP-011/CP-012 remain closed; CP-013 cannot resume until this follow-up gate is PASS and its separate rollout approval remains valid.

- [ ] Verify all CP-015 PRs are based on `origin/main`, have green CI, and contain the required evidence.
- [ ] Build a new immutable release manifest with UI/worker/sidecar digests and rollback version.
- [ ] Run the release verification and rollback dry-run; do not create production state.
- [ ] Record the final gate in `docs/evidence/CP-015F-YYYY-MM-DD.md`.

## Revised execution order

1. Keep historical CP-001 through CP-012 evidence immutable; verify every new PR/CI gate.
2. Finish CP-009/CP-014 heartbeat/authority dependencies before adding proxy state migrations.
3. Run CP-015A, then CP-015B.
4. Run CP-015C and CP-015D in parallel only after CP-015B and their file ownership is confirmed; they must not share mutable files.
5. Run CP-015E on disposable resources only.
6. Run CP-015F as a new release/rollback gate; do not reopen closed CP-011/CP-012 merely because the implementation changed.
7. Run CP-014J cleanup/recreate acceptance only after fresh destructive approval if the final plan still requires cleanup.
8. Resume CP-013 staged production rollout only after explicit approval; stop after each stage for dashboard, traffic, egress, DNS, heartbeat, lease, and rollback evidence.

## Required verification commands

Every implementation task must run from its own worktree:

```powershell
python -m pytest -q <focused tests>
uv run ruff check .
uv run ruff format --check .
python -m compileall -q app tests
git diff --check
```

Runtime canaries additionally require packet evidence for TCP, DNS/DoH, IPv6, UDP, and direct fallback, plus before/after container identity, volume, restart count, provider dashboard state, and rollback result. No task may claim `production-ready` while any required gate is `FAIL`, `INCONCLUSIVE`, or an unexplained CI failure.

## Goal handoff rule

The paused goal is not safe to resume with its old text alone: its durable objective currently points at the pasted continuation prompt, while this addendum is new. Do not create a second goal merely to hide the gap. Resume the existing goal only with a continuation message that explicitly reads this addendum, verifies current Beads/PR/CI state, and treats CP-015A–F as mandatory gates before CP-011 or CP-013. If the UI cannot attach that continuation to the paused goal, create one new goal from the complete merged plan and mark the old goal as superseded; do not run both.
