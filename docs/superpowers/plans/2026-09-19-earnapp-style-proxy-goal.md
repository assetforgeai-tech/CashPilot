# EarnApp-Style Proxy Runtime Standardization Goal

> **For agentic workers:** Execute this plan task-by-task with local test gates; preserve unrelated dirty changes and stop at explicit live blockers.

**Goal:** Standardize proxy-provider network transport around the verified EarnApp-style in-container route, then prove leak-free operation with bounded Azure canaries.

**Current proxy policy (2026-09-20):** Proxy Pool currently contains VN residential proxies only. EarnApp VN policy enables `macos` and `ios`; `ubuntu` is disabled. Ubuntu remains unscheduled until an eligible non-VN residential proxy exists; its absence is expected, not a deployment failure.

**Authoritative UI selection (2026-09-20):** The dashboard currently has VN
selected for EarnApp and ticks only `macos` and `ios`. Deployment must derive
the platform set from this persisted selection; it must not infer Ubuntu from
the presence of an IPv4 slot or silently broaden the country scope.

**Architecture:** Share only proxy transport, DNS/DoH readiness, firewall fail-closed behavior, egress verification, watchdog, and route rotation primitives. Keep provider-specific account, identity, allocator, lifecycle, and payment policies behind provider adapters.

**Tech Stack:** Python application/runtime, Docker, redsocks, local DNS/DoH, iptables, pytest, Azure workers `118903` and `118904`.

## Global Constraints

- Pawns and EarnApp remain separate lanes; MYST/NKN remain direct-only.
- No `test-sing`, `test-us`, `sing`, or `eapp`.
- No fleet mutation before local tests and one-node canary evidence pass.
- No production-ready claim without packet-level live evidence.

---

## Objective

Standardize every provider runtime that uses a proxy around the verified
EarnApp-style in-container network route, fix the route's remaining defects,
and prove the result before production rollout.

## Latest agreed direction

- Treat the EarnApp fake-proxy implementation as the baseline for shared
  network transport because it already covers redsocks, local DNS/DoH,
  fail-closed firewalling, egress verification, and leak prevention.
- Reuse only the transport/readiness/watchdog layer. Do not copy EarnApp
  account, token, link, identity, country, usage, or allocator behavior into
  other providers.
- Pawns remains a separate proxy lane with its own allocation and `ip_used`
  handling. EarnApp remains account-scoped and sticky. A shared route layer
  must not release or reassign either provider's ownership state.
- Proxy rotation is part of this goal: confirmed proxy failure rebuilds the
  route with the provider's allocator policy, verifies the new egress, then
  restarts the provider. It must never be triggered by a single noisy probe.
- Runtime verification may use a disposable, explicitly fault-injected staged
  canary. The injected failure must be isolated from the live earning node and
  must enter the same normal Worker API/lifecycle state machine; it is valid
  evidence of orchestration behavior, not evidence of real proxy health.
- A real outage is not required to prove the rotation path. The disposable
  canary may emit deterministic `proxy_health=unhealthy` evidence with
  `direct_fallback_blocked=true`; the repeated-health gate, provider allocator,
  staged replacement, dashboard deletion and cleanup must still execute.
- The owner-only endpoint `/api/admin/earnapp/disposable/{logical_node_id}/inject-proxy-failure`
  is the live entrypoint for this proof. It accepts only disposable slugs,
  worker `118903`/`118904`, a matching generation/device/proxy CAS tuple, and
  an explicit nonce; it records three health samples before calling the real
  `_rotate_unhealthy_earnapp_node` lifecycle path.
- MYST and NKN stay direct-only. No generic/raw Docker fallback is allowed
  for proxy providers; provider-specific exceptions require explicit policy,
  tests, and live evidence.
- Evidence must distinguish configuration/test confidence from packet-level
  live proof. Unknown live behavior remains `unverified`.
- Code-path acceptance does not require a naturally failing production proxy.
  Deterministic disposable inputs may stand in for proxy health, dashboard
  status, and worker responses when they traverse the real allocator,
  lifecycle, durable transaction, queue, and CAS adapters. Record those facts
  as orchestration evidence; reserve provider-health and earnings claims for
  authenticated live observations.

## 2026-09-20 checkpoint

- Confirmed VN-only Proxy Pool policy: EarnApp `macos`/`ios` enabled; Ubuntu
  remains disabled until non-VN residential inventory exists.
- Fixed and deployed worker orphan cleanup to `118904` using immutable image
  `ghcr.io/assetforgeai-tech/cashpilot-worker:earnapp-orphan-cleanup-20260922`
  (`sha256:0d8bb3892c3be054bc31644e92b25b9fbcf0de0686025a20882868a682442007`).
- Verified worker healthy with restart count `0`; promoted disposable runtime
  is physically absent after cleanup. Provider workloads were not mutated.
- Local regression gate: `46 passed` (`test_proxy_sidecar_runtime.py`,
  `test_earnapp_staged_recovery.py`).
- Remaining gates: authenticated provider workload/dashboard evidence, DNS/DoH,
  IPv6/UDP/direct-fallback checks, watchdog, retry/rollback, and reboot
  persistence. Do not claim completion before these gates.

## 2026-09-20 controlled canary refresh

- Worker artifact parity was corrected: the worker now uses the current Mac
  asset contract `fd2fbbe2ff45`, not the stale `801686a44062` contract. Current
  immutable worker image:
  `ghcr.io/assetforgeai-tech/cashpilot-worker:earnapp-orphan-cleanup-20260920d`
  digest `sha256:9627ca9a48ffa25bbfbf2d21b47806ed3e75bea41ac42da6de573cbfd17feaa6`.
- Fixed cleanup semantics so a canonical delete cannot remove a candidate that
  still has its stage name; only a promoted container renamed to the canonical
  name is eligible for orphan cleanup. Regression tests cover both cases.
- Rotation-15 completed the real disposable state machine: `3/3` unhealthy
  samples, staged replacement, workload assumption, old-device cleanup,
  generation `1 -> 2`, proxy `12829 -> 12942`, CAS promotion, and normal API
  cleanup.
- Rotation-16 proved runtime transport/watchdog: proxy egress matched, local
  DNS/DoH, IPv6 fail-closed, firewall DROP chains, redsocks kill/restart, and
  provider recovery. Disposable cleanup completed through normal API.
- Focused local tests after cleanup fix: `357 passed`; full regression:
  `3396 passed, 7 skipped`. Production workloads remained untouched.

## 2026-09-20 disposable artifact A/B guard

- Added an immutable allowlist for the two read-only production-proven Apple
  artifacts: macOS `asset-02dc8060a352` and iOS `asset-28b1be5d6668`.
- Image override is accepted only for `earnapp-disposable-*` Apple canaries;
  production slugs, Ubuntu, and arbitrary image references remain rejected.
- Local combined gate after this change: `299 passed` across EarnApp canary,
  auto-deploy, and network-contract tests.
- Live deployment remains pending until Worker API confirms the selected image
  is preloaded on worker `118904`.
- Read-only server authority now confirms worker `118904` is running the
  production-proven `asset-801686a44062` macOS image with workload, egress,
  packet, and reboot evidence. This tag is allowlisted for disposable A/B only.
- Server status currently lists the target as running; no disposable node has
  been created yet. The new override code is not live until the normal image
  release pipeline publishes and deploys the server UI.

## Non-negotiable boundaries

- Pawns and EarnApp are separate proxy lanes.
- Pawns keeps its provider-private allocation and `ip_used` policy.
- EarnApp keeps account-scoped sticky proxy ownership, account queue, token/link
  policy, and its own banned/offline/usage lifecycle.
- Shared code covers only network transport and readiness, never account or
  proxy allocation policy.
- MYST and NKN remain direct-only; do not force them through fake-proxy.
- Do not use `test-sing`, `test-us`, `sing`, or `eapp`.
- Live scope is Azure workers `118903` and `118904` only.
- Preserve unrelated dirty worktree changes.
- No fleet restart, rotate, recreate, or redeploy until local tests and a
  one-node canary gate pass.
- A live healthy node must not be damaged solely to manufacture a failure; use
  a disposable staged runtime for deterministic rotation-path verification.

## Target fake-proxy contract

Each proxy provider container owns, or is wrapped by a migration-compatible
runtime that owns:

1. Resolve/pin the proxy endpoint using a tightly scoped bootstrap path.
2. Start `redsocks` with the leased HTTP/SOCKS5 endpoint.
3. Start local DNS forwarder only after `redsocks` is ready.
4. Forward DNS upstream through HTTPS DoH over `redsocks`.
5. Redirect provider TCP through `redsocks` with `iptables`.
6. Allow only loopback, established traffic, and the pinned proxy endpoint.
7. Block IPv6.
8. Block UDP by default; no direct UDP exception unless a provider-specific
   proxy-UDP implementation is proven and declared in policy.
9. Block direct TCP fallback.
10. Verify observed egress equals the leased proxy egress IP before starting
    the provider binary.
11. Start provider only after all readiness checks pass.
12. Watchdog `redsocks`, DNS forwarder, firewall rules, and egress health.

## Known EarnApp route defects to fix before reuse

- DoH currently starts before `redsocks`; reorder startup behind readiness.
- Add explicit readiness checks for proxy TCP, local DNS, DoH, and egress IP.
- Pin resolved proxy IPv4 where possible; never permit arbitrary direct DNS.
- Reapply/verify firewall rules after process restart.
- Fail closed if `redsocks` or DNS forwarder exits.
- Keep the existing EarnApp identity, OS emulation, account, link, and token
  behavior unchanged.

## Rotation contract

Proxy death must rebuild route state, not merely restart the provider process:

```text
confirmed proxy failure
  -> stop provider
  -> remove old redsocks/DNS/iptables state
  -> allocate replacement using provider-specific policy
  -> create route with new endpoint
  -> verify egress/DNS/fail-closed
  -> start provider
  -> record evidence
```

## Handoff checkpoint — 2026-09-19

The local implementation and regression gates are complete for this checkpoint.
Do not repeat them unless a later change invalidates the tests.

### Verification refresh — 2026-09-19

- Focused route/canary tests: `227 passed`.
- Full suite: `3371 passed, 7 skipped` in `230.47s`.
- Read-only server authority confirmed worker keys for `118903` and `118904`;
  no credential was written to the repository.
- A normal one-node canary request was attempted against the unprotected
  `earnapp-proxy-w118904-ipv4-003`, preserving its account, identity volume,
  device ID, and proxy. The worker returned `403 EarnApp image is not the
  verified Mac canary image` before mutation. This is not a node failure: the
  live worker is still on the older `1.53.12` release and its allowlisted
  image contract predates `asset-801686a44062`.
- The request was repeated with both the private GHCR image name and the local
  image name; both were rejected at validation, confirming the blocker is the
  stale worker contract/preload state, not GHCR authentication or node state.
- No live node was changed by the failed canary requests.

### Completed locally

- `app/earnapp_runtime.py`: redsocks readiness now precedes local DNS/DoH;
  Ubuntu/macOS source runtimes use a synchronous DoH readiness gate; iOS waits
  for redsocks before DoH/provider handoff; DNS remains loopback-local and
  fail-closed.
- `tests/test_earnapp_canary_contract.py`: source-runtime readiness regressions
  covered, including the Ubuntu marker `iptables REDSOCKS chain installed`.
- `services/bandwidth/earnapp.yml`: image contract points to the current
  generated asset hash.
- `app/proxy_runtime.py`, provider policy labels, and orchestrator evidence
  parsing are present; EarnApp is `in_container`, Pawns remains
  `singbox_compat` pending its own canary, MYST/NKN are `direct_only`.
- Verification passed: `pytest -q` => `3368 passed, 7 skipped`; focused
  EarnApp/proxy => `224 passed`; provider network contracts => `68 passed`.

### Azure read-only evidence

- Scope is workers `118903` and `118904` only. No `test-sing`, `test-us`,
  `sing`, or `eapp` was used.
- `docs/evidence/azure-egress-probe-2026-09-19.json` records 14 representative
  proxy runtimes per worker, each repeated `3/3` successfully with stable
  HTTPS egress.
- Worker `118903`, EarnApp runtime `earnapp-proxy-w118903-ipv4-001`: container
  `172.17.0.54`, observed egress `116.98.235.49`; IPv6 blocked; DNS points to
  `127.0.0.1`; `CP_EARNAPP_OUT`/`CP_EARNAPP6_OUT` fail closed; DNS UDP/TCP
  redirects to local `1053`; packet capture observed container TCP only to
  proxy `116.98.186.81:23761`, with no direct target traffic.
- Worker `118904`, EarnApp runtime `earnapp-proxy-w118904-ipv4-001`: container
  `172.17.0.33`, observed egress `116.98.188.106`; IPv6 blocked; local DNS and
  fail-closed chains present; proxy endpoint `116.98.186.81:24409`. The final
  packet-capture poll must be completed before declaring this worker's packet
  evidence complete.
- These results prove repeated HTTPS reachability and partial packet-level
  containment only. They do not yet prove full DNS/DoH, UDP, direct-fallback,
  watchdog, rotation, or reboot persistence.

### Exact next actions

1. Append the final worker `118904` packet-capture output to
   `docs/evidence/proxy-runtime-contract-2026-09-19.md`.
2. Publish and preload a worker image containing the current verified EarnApp
   image contract on exactly workers `118903` and `118904`; preserve worker
   data volumes and rollback image digests.
3. Re-run one-node checks: egress, local DNS/DoH, IPv6, UDP, direct-fallback,
   watchdog, rotation, and reboot persistence.
4. Publish the updated EarnApp canary image only after artifact provenance and
   image hash verification.
5. Deploy exactly one representative node through the normal worker API;
   reconcile its provider dashboard before any expansion.
6. Expand by provider/topology only after the one-node gate passes. Keep
   EarnApp and Pawns allocation/ownership policies isolated.

### Safety stop conditions

- Stop on missing worker-scoped authorization, missing provider credentials,
  ambiguous destructive live state, or failed packet evidence.
- Do not bulk restart, rotate, recreate, redeploy, or clean the fleet before
  the one-node gate passes.
- Do not claim provider or production readiness from local tests alone.

### Rotation invariants

- One transient probe never rotates.
- Require repeated health failure.
- EarnApp replacement stays account-scoped/sticky.
- Pawns replacement stays Pawns-private and respects `ip_used`.
- Other providers use their own allocator and release/quarantine rules.
- Old proxy release must never cross account/provider ownership boundaries.

## Execution order

### Controlled disposable cleanup and policy checkpoint — 2026-09-20

- Confirmed the active proxy-pool policy is VN-only with VN enabled for
  macOS/iOS; Ubuntu remains correctly rejected unless a non-VN residential
  proxy is eligible. No validator was loosened.
- Disposable `earnapp-disposable-w118904-rotation-04` was removed through the
  normal Worker API using its exact generation/device CAS tuple. Database
  rollback returned it to `PLANNED`; its stale provider-instance row was then
  removed through the normal lifecycle database API. No production node was
  touched.
- A fresh disposable macOS deployment (`rotation-05`) and iOS deployment
  (`rotation-06`) both failed at the worker deployment boundary with HTTP 500
  before a runtime was created. This is a worker image/preload or contract
  blocker, not evidence of proxy failure or a route leak. Worker/API logs must
  be collected before another mutation.
- Local regression gate after this checkpoint: `319 passed` across canary,
  node-health, staged-recovery, and proxy-health suites.
- Staged replacement remains **unverified**. Do not claim promotion, remote
  dashboard deletion, or cleanup success until a disposable macOS/iOS runtime
  can be deployed on worker `118904` and traverses the full state machine.

### Controlled-assumption checkpoint — 2026-09-19 (continued)

- Rebuilt and redeployed the fault-injection UI image from the current dirty
  source. The container reached `running|healthy` on the CashPilot server.
- Focused regression suite remains green: `106 passed`.
- The first disposable Ubuntu rotation candidate was VN; the worker rejected
  it with HTTP 403 because the older runtime contract required non-VN. That
  exposed a policy mismatch, not a worker failure. The current code keeps the
  explicit Settings country/OS policy and does not silently rewrite it in the
  allocator.
- A second disposable deploy was refused with `no eligible residential
  EarnApp proxy available`; inspection found the pool's available candidates
  are already account-sticky/leased or the disposable provider row is stale.
  No production lease was released or reassigned.
- Cleanup through the normal worker API and DB rollback returned the first
  disposable logical node to `PLANNED`; its runtime containers were removed.
- Staged promotion is still **unverified**. Do not claim replacement success
  until a disposable candidate is available and the full stage/link/verify,
  old-device-delete, promote, cleanup path completes.

## Progress refresh — 2026-09-19

- Heartbeat authority blocker fixed: authenticated EarnApp provider-state IDs
  now protect against transient inventory misses, and exact-affinity rebind
  restores a `PLANNED` row only when its running provider instance, worker,
  generation, device ID, preferred proxy, eligibility, and lease checks match.
- Verification after the fix: focused route/canary `230 passed`; lifecycle and
  provider-instance coverage `94 passed`; full suite `3375 passed, 7 skipped`.
- UI release deployed to the CashPilot server:
  `ghcr.io/assetforgeai-tech/cashpilot:earnapp-heartbeat-rebind-20260919`,
  digest `sha256:2b8fb17e60f661e49fcf77587c6e34b05dbb88b4468a3ae57cbc427837ad73ad`.
- Worker `118904` is pinned persistently to
  `ghcr.io/assetforgeai-tech/cashpilot-worker:earnapp-route-20260919-fixed`,
  digest `sha256:38a5d571227657f61e680261d24a2552d143209c6f87912e469ace3b53352114`.
- Canary `earnapp-proxy-w118904-ipv4-003` is `ACTIVE`, preserves device
  `sdk-mac-10fd4755ccd48550307249a49f86d445`, proxy `12970`, and egress
  `116.98.181.156`; provider snapshot reports `online=true` and earnings.
- Watchdog fault injection, worker reboot persistence, local DNS/DoH, IPv6
  blocking, TCP redirect, and non-DNS UDP DROP are proven in the evidence log.
- Remaining live gate: controlled EarnApp proxy rotation/replacement and
  provider-dashboard old-node cleanup. Do not expand provider rollout until
  that gate is completed or explicitly recorded as unverified.

### Phase 1 — Audit

- Read the complete EarnApp route implementation and tests.
- Extract reusable route primitives without copying identity/account logic.
- Build provider matrix: proxy-only, hybrid, direct-only, UDP requirements,
  manual runtime, allocator and lifecycle exceptions.
- Mark unknown live evidence as `unverified`, never `pass`.

### Phase 2 — Implement shared runtime

- Create the smallest shared `app/proxy_runtime.py`.
- Refactor only network route primitives from `app/earnapp_runtime.py`.
- Drive provider behavior from `provider_runtime.py`.
- Replace provider-name hard-coding in orchestration.
- Keep sing-box only as migration compatibility until each provider passes the
  new route canary.

### Phase 3 — Tests

- Add failing tests first for startup ordering and fail-closed behavior.
- Test DNS-before-redsocks rejection, IPv6 block, UDP block, direct fallback
  block, egress mismatch, watchdog failure, and route rebuild on rotation.
- Test Pawns/EarnApp allocator isolation.
- Run focused tests, then full suite.

### Phase 4 — Live canary

- Use only workers `118903` and `118904`.
- Select one representative node per proxy topology/provider group.
- Run repeated read-only probes before mutation.
- Capture runtime logs, observed egress, DNS/IPv6/UDP/direct-fallback evidence.
- Change one canary only after local gate passes.
- Do not bulk rotate or redeploy on a single transient failure.

### Phase 5 — Provider rollout

- Roll out provider by provider.
- Reconcile CashPilot runtime inventory with provider dashboard/traffic.
- Keep failed providers in `attention` with evidence and root cause.
- Do not mark production-ready until all required proxy lanes pass.

### Phase 6 — Release

- Build/pin UI and worker images.
- Deploy through the normal release path.
- Verify worker identity, container counts, restart counts, and health.
- Verify proxy route evidence after reboot and after rotation.
- Publish final evidence and residual-risk report.

## Required evidence

- Source/provider matrix.
- Focused and full test output.
- One canary per topology.
- Expected versus observed egress IP.
- DNS/DoH/DoT behavior.
- IPv6 and UDP block proof.
- Direct-fallback proof.
- Rotation proof with old/new proxy IDs.
- Pawns/EarnApp lane isolation proof.
- Reboot persistence proof.

## Success criteria

- All proxy providers use the shared EarnApp-style route or an explicitly
  documented, tested exception.
- No direct IP/DNS/IPv6/UDP leak in packet-level canary evidence.
- Proxy rotation rebuilds route state and preserves provider-specific policy.
- EarnApp and Pawns never share account/allocation state.
- Full test suite passes.
- Production release has pinned artifacts and rollback evidence.

## Current checkpoint

### Allocator ownership and disposable rotation-12 — 2026-09-19

- Confirmed the active pool policy is residential VN-only; macOS/iOS are the
  only EarnApp platforms eligible for this pool. Ubuntu remains rejected until
  a non-VN residential endpoint exists.
- Added sticky-egress exclusion to both read-only candidate selection and the
  transactional reservation path. A live egress owned by another EarnApp
  account can no longer be selected by a later rotation race.
- Focused regression gate passed: `110 passed` across node health, provider
  inventory, and staged recovery suites.
- Rebuilt the UI from synchronized source after discovering the server source
  lacked `app/earnapp_policy.py`; the first rebuild crash-looped and was rolled
  back without node mutation. The synchronized build is healthy with restart
  count `0`.
- Disposable macOS `earnapp-disposable-w118904-rotation-12` was deployed on
  worker `118904`, account `470`, proxy `12931`, with a fresh device. The
  authenticated workload check was not positive, so this is not provider
  earnings evidence.
- The deterministic failure endpoint accepted exactly three unhealthy samples
  and completed worker promotion: generation `1`/proxy `12931` became
  generation `2`/proxy `12940`, with a fresh device. The replacement
  transaction was consumed; the runtime was removed through the normal API,
  the node returned to `PLANNED`, and its provider-instance row/active lease
  were removed/released. This proves allocator, repeated-health gate, worker
  promotion, CAS cleanup, and rollback behavior only.
- Old disposable `rotation-11` had no active runtime or transaction; its stale
  provider-instance row was removed through `remove_provider_instance`. No
  production node was touched.

Remaining live gate: authenticated dashboard/workload verification for a
disposable runtime remains unverified; current worker image/runtime contract
must be reconciled before claiming provider-side success.

### Staged promotion race fix — 2026-09-20

- Added a regression test proving a staged EarnApp container must not satisfy
  canonical lookup after the old runtime is deleted.
- Root cause confirmed on Azure worker `118904`: staged containers carry
  `cashpilot.service=<canonical>`; label fallback then treated the stage as
  canonical and removed it during the promotion gap.
- Fixed `_find_earnapp_runtime_container` to ignore containers carrying
  `cashpilot.earnapp.stage_slug` during canonical lookup.
- Focused regression gate: `109 passed` across node health, provider inventory,
  and staged recovery suites.
- Rebuilt/redeployed worker `118904` with the fix; worker healthy. UI was also
  rebuilt from the full source tree with the inventory transaction guard and is
  healthy.
- Disposable rotation-11 reached worker promotion successfully after the fix;
  DB promotion remained retryable because its candidate egress was sticky-owned
  by a different disposable account. This is allocator/ownership evidence, not
  a runtime race. The disposable state was cleaned through Worker API/CAS.
- Rotation remains **unverified end-to-end** until a fresh disposable node uses
  a candidate owned by the same account and reaches `PROMOTED -> CLEANED`.

### Live evidence refresh — 2026-09-19

- Corrected LF UI/worker artifacts are deployed and healthy on the CashPilot
  server; rollback compose copies remain present.
- Target `earnapp-proxy-w118904-ipv4-003` passed the earnings-cycle gate with
  `workload_verified`, `online=true`, `banned=false`, usage delta `217611`,
  and egress `116.98.181.156`.
- Packet capture showed bidirectional payload only between the target namespace
  and pinned proxy `116.103.141.85:23826`; DNS is loopback `127.0.0.1:1053`,
  IPv6 is blocked, direct fallback times out, and non-DNS UDP is fail-closed.
- Azure reboot of worker `118904` preserved the target container, identity,
  proxy, egress, workload, and firewall/watchdog processes.
- Rotation remains `unverified`: the target proxy is healthy. Do not create a
  synthetic failure or rotate a healthy earning node. Execute the staged
  replacement only after repeated real proxy failure or authenticated
  dashboard ban/egress mismatch, then capture old/new device and DB ownership
  evidence.

### Execution refresh — 2026-09-19

- Full local suite after durable replacement changes: `3379 passed, 7 skipped`.
- Focused EarnApp staged/health suite: `88 passed` across the staged recovery,
  node health, route, and provider network contracts.
- Added durable `earnapp_replacement_transactions` state storage and retryable
  states through `PROMOTED_PENDING`; worker promotion is idempotent when the
  canonical state already reflects the promoted runtime.
- Account-bound rotation now uses staged identity/runtime, serialized account
  link verification, remote-delete confirmation, worker promotion, and DB CAS
  promotion. The old runtime/device remains untouched until staged workload
  verification passes.
- The live rotation gate is still `unverified`: no destructive live rotation
  was executed in this refresh. The next mutation remains exactly one canary
  rotation on `earnapp-proxy-w118904-ipv4-003`, after current worker image/API
  authorization and dashboard reconciliation are confirmed.

### Packet evidence refresh - 2026-09-19 12:55 UTC

- Artifact and worker health gates rechecked: UI/worker LF images healthy;
  both Azure workers run the corrected worker digest.
- Target `earnapp-proxy-w118904-ipv4-003` collector snapshot repeated three
  times: online, not banned, country VN, usage present, egress
  `116.98.181.156`.
- Read-only packet capture confirmed local DNS, pinned proxy-only TCP payload,
  IPv6 block, non-DNS UDP block with DROP counter increment, and no direct
  target/VPS egress.
- Rotation remains unverified by design: the required target is healthy, so
  no synthetic failure or destructive mutation was performed.

- Worktree: `D:\1. WORK_true\CashPilot\repo-spide-release-20260916`.
- Branch: `fix/spide-production-closeout-20260916`.
- The worktree is intentionally dirty; preserve every unrelated/user change.
- Existing generic sing-box route remains migration compatibility only.
- Existing full-suite baseline before this goal: `3348 passed, 7 skipped`.
- A new RED test exists at `tests/test_proxy_runtime.py`.
- `app/proxy_runtime.py` now exists with the minimum route contract; focused
  tests are GREEN.
- EarnApp source-runtime DoH gate is injected after reference redsocks setup
  for Ubuntu/macOS; iOS waits for redsocks before starting DoH.
- Current local verification: `3368 passed, 7 skipped`; focused
  EarnApp/proxy suite `224 passed`; network contract suite `68 passed`.
- `provider_runtime.py` now exposes an explicit `proxy_transport` policy and
  orchestration labels each proxy runtime with it. EarnApp uses
  `in_container`; other proxy providers remain `singbox_compat` until their
  image-specific canary proves the shared route; MYST/NKN are `direct_only`.
- Immediate next action: resolve worker-scoped live-probe authorization, then
  collect read-only one-node canary evidence before any fleet mutation.
- Live preflight confirmed direct worker health for `118903` and `118904`.
  Server API health remains `404` and the supplied shared bearer is `401`, but
  confirmed per-worker keys were recovered internally from the server DB.
- Read-only egress probe evidence now exists for one representative proxy
  runtime per family, repeated `3/3` on both workers. Packet-level DNS/IPv6/
  UDP/direct-fallback proof remains the next gate.
- Read-only refresh at `2026-09-19 20:22 UTC` kept all sampled runtimes
  running. Worker `118903` had no confirmed failures; worker `118904` had one
  confirmed `3/3` failure for `urnetwork-proxy-w118904-proxy-001`, whose logs
  show provider `auth error ... Timeout`, so no route rotation was triggered.
- Packet-level one-node probes at `2026-09-19 20:29 UTC` captured only the
  pinned proxy endpoints for EarnApp containers on both workers; IPv4 egress
  matched the proxy, IPv6 curl was blocked, and no direct target traffic was
  observed. Explicit UDP-drop counters and DoH-upstream proof remain open.
- UDP probes at `20:31 UTC` incremented the final fail-closed DROP counter on
  both EarnApp containers; local DNS was redirected to `127.0.0.1:1053` and
  the helper's HTTPS upstream was `cloudflare-dns.com/dns-query`. Watchdog,
  live rotation, and reboot persistence remain open.
- Watchdog fault injection at `20:39 UTC` exposed the old deployed image's
  missing parent watchdog: killing `redsocks` left the provider alive. The
  generated wrapper now launches the child under a watchdog with regression
  coverage (`227 passed` focused); the canary was restored by one container
  restart. New-image deployment and automatic recovery proof remain open.

## Rotation relationship

This change directly affects proxy rotation. Rotation is not a provider-only
restart and must not reuse stale route state. After repeated, confirmed proxy
failure, CashPilot must stop the provider, tear down the old route, obtain a
replacement through that provider's existing lane policy, install and verify
the new route, then start the provider. EarnApp and Pawns keep their separate
allocation rules; only the route lifecycle is shared.

No rotation may be triggered by one noisy probe. No proxy may cross an account
or provider ownership boundary during release/replacement.

## Durable rotation checkpoint

The account-bound staged replacement state machine is implemented and locally
verified. Do not rebuild it or restore the removed `staged_verified` boolean.

Persisted states:

```text
PREPARED
STAGED
VERIFIED
OLD_DELETE_CONFIRMED
PROMOTED_PENDING
PROMOTED
CLEANED
FAILED
```

Implemented behavior:

- Reserve the replacement through the existing provider/account allocator.
- Create a distinct staged identity/profile and staged Docker runtime.
- Serialize link and verification through the EarnApp account queue.
- Require authenticated, present, online, not banned, correct egress, and
  verified workload before touching the old runtime.
- Persist remote-device deletion confirmation before local removal.
- Retry ambiguous worker promotion through `PROMOTED_PENDING` and accept the
  worker's idempotent `already_promoted` result.
- Promote device, proxy, generation, lease, and account ownership atomically.
- Remove only candidate resources after failed staged verification.
- Preserve the old runtime on verification or remote-delete failure.

Verification at this checkpoint:

```text
focused staged/health tests: 87 passed
full suite: 3379 passed, 7 skipped
python -m compileall -q app: passed
```

The first remaining live mutation is exactly one controlled rotation of
`earnapp-proxy-w118904-ipv4-003`. Record old/new device IDs, proxy IDs, egress,
DNS/IPv6/UDP/direct-fallback, provider-dashboard deletion, DB lease/ownership,
retry behavior, and reboot persistence. Expand only after this evidence passes.

## Artifact checkpoint and recovery

The first staged UI/worker build exposed a Windows CRLF checkout defect:
`/entrypoint.sh` entered the Linux images with CRLF, causing
`[FATAL tini] exec /entrypoint.sh failed: No such file or directory`.

- The server was rolled back successfully to the stable UI image
  `ghcr.io/assetforgeai-tech/cashpilot:earnapp-heartbeat-rebind-20260919`.
- The server worker was restored to
  `ghcr.io/assetforgeai-tech/cashpilot-worker:earnapp-route-20260919-fixed`.
- Azure workers and live nodes were not changed by this incident.
- The corrected worker image was published as
  `ghcr.io/assetforgeai-tech/cashpilot-worker:earnapp-staged-20260919-lf`,
  digest `sha256:40d5e86765fc5a9cd4abaa41513e308af3ddeb69f7661f396a15b6c78132ba17`.
- The corrected UI image target is
  `ghcr.io/assetforgeai-tech/cashpilot:earnapp-staged-20260919-lf`; its build
  digest is `sha256:b537d76f8ef1a4e25d3e48ef2510e6f5cc68912a2d6f1f6e38cbd2ccf62459f4`.

Never deploy either corrected image without inspecting `/entrypoint.sh`,
running an isolated container smoke test, and confirming health for 30-60
seconds. Preserve `/data`, `/fleet`, current compose overrides, and rollback
digests.

Artifact gate completed on the server at `2026-09-19 09:26-09:28 UTC`: both
corrected containers are healthy, UI collection completed, and worker heartbeat
returned HTTP 200. The stable compose files remain available as
`.pre-staged-lf` rollback copies. No Azure node was mutated by this deployment.

## Goal execution gates

1. Finish and verify the local route implementation, including DoH startup
   ordering for Ubuntu and macOS source runtimes.
2. Run focused route/provider tests, then the complete test suite.
3. Run one-node canaries only on Azure workers `118903` and `118904`; collect
   packet-level egress, DNS, IPv6, UDP, and direct-fallback evidence.
4. Reconcile one canary against its provider dashboard before expanding.
5. Roll out provider-by-provider only after the relevant topology gate passes.
6. Stop at missing credentials, unavailable worker-scoped authorization, or
   destructive live ambiguity; report the blocker instead of guessing.

Do not restart, rotate, recreate, redeploy, or bulk-clean the fleet before
steps 1-4 pass. Do not use `test-sing`, `test-us`, `sing`, or `eapp`.

## Resume prompt

```text
Tiếp tục goal theo
docs/superpowers/plans/2026-09-19-earnapp-style-proxy-goal.md.

Giữ nguyên toàn bộ thay đổi hiện tại. Dùng EarnApp redsocks + local DNS + DoH
qua proxy + iptables fail-closed làm chuẩn fake-proxy cho mọi provider dùng
proxy. Chỉ chia sẻ network transport/readiness/watchdog; không đưa identity,
account, link, token hoặc allocator EarnApp vào runtime dùng chung.

Giữ Pawns và EarnApp ở hai lane riêng. MYST/NKN direct-only. Live chỉ dùng
Azure workers 118903 và 118904; tuyệt đối không dùng test-sing, test-us, sing,
eapp. Không restart/rotate/recreate/redeploy hàng loạt trước khi test local và
canary một node đạt.

Bắt đầu từ checkpoint hiện tại: kiểm tra artifact UI build đang chờ, xác nhận
LF/shebang của cả UI và worker, smoke-test cô lập, rồi mới deploy có rollback.
Không lặp lại bước tạo `app/proxy_runtime.py` hoặc state machine nếu file/test
đã tồn tại và xanh. Sau đó canary một node mỗi topology, thu bằng chứng egress,
DNS/DoH/DoT, IPv6, UDP, direct fallback, watchdog, rotate và reboot persistence.

Rotate chỉ sau lỗi proxy được xác nhận lặp lại: stop provider, xóa route cũ,
lease theo policy riêng của provider, dựng route mới, verify, start provider,
ghi evidence. Không rotate vì một probe thất bại. Không làm mất sticky ownership
EarnApp hoặc policy ip_used của Pawns.

Không tuyên bố provider/production-ready nếu chưa có test và bằng chứng live.
Nếu gặp credential thiếu hoặc hành động live không thể đảo ngược, dừng đúng tại
blocker và báo rõ; các phần độc lập khác vẫn tiếp tục.
```

## Final execution directive

This is the authoritative goal prompt for the next execution session. The
requested change is transport standardization, not a rewrite of provider
business logic:

1. Treat the verified EarnApp in-container route as the reference for every
   provider that uses a proxy: redsocks, loopback DNS/DoH through the proxy,
   iptables fail-closed policy, IPv6/UDP/direct-fallback blocking, pinned
   proxy endpoint, egress verification, and parent watchdog.
2. Extract or reuse only those network primitives. Do not copy EarnApp
   identity generation, account/token/link queueing, country/usage policy,
   sticky ownership, or allocator behavior into another provider.
3. Preserve lane isolation: EarnApp keeps account-scoped sticky proxy
   ownership and serialized link/retry; Pawns keeps its independent allocator
   and `ip_used`; MYST/NKN remain direct-only.
4. Make proxy rotation use the existing provider allocator. Rotate only after
   repeated confirmed route failure: stop provider, tear down old route, lease
   replacement in the same provider/account lane, build and verify the new
   route, then restart provider. Never rotate on one noisy probe or cross
   EarnApp/Pawns ownership boundaries.
5. Run local focused tests, then the full suite. Use only Azure workers
   `118903` and `118904` for live checks. Never use `test-sing`, `test-us`,
   `sing`, or `eapp`.
6. Before any fleet mutation, pass one-node canary gates for each relevant
   proxy topology: packet-level egress, DNS/DoH, IPv6, UDP, direct fallback,
   watchdog recovery, rotation, reboot persistence, and provider-dashboard
   reconciliation.
7. Resolve the current protected-node/API authorization blocker through the
   normal worker canary route. Do not bypass guards with raw Docker. If the
   route cannot authorize a one-node canary, document the blocker and stop
   mutation; continue read-only audit and local verification.
8. Publish/pin the three verified private GHCR EarnApp images only after
   digest and provenance checks. Deploy one node, collect evidence, then
   expand provider-by-provider.

Completion requires passing tests plus live evidence. Configuration-only
confidence is not production readiness.

## Ownership repair checkpoint - 2026-09-19

- Root cause confirmed for repeated worker `404 EarnApp node state not found`:
  state JSON files under `/data/earnapp-nodes` were root-owned mode `0600`,
  while the API process runs as `cashpilot` UID 1000.
- Repaired both live workers with `chown -R cashpilot:root
  /data/earnapp-nodes`; no provider container, identity, UUID, proxy, or
  lifecycle mutation was performed.
- Authenticated worker presence now returns HTTP 200 and `main_present=true`
  for all Docker EarnApp nodes on workers `118903` and `118904`.
- Added startup guard in `entrypoint.sh` so future worker restarts repair the
  state ownership automatically. Regression test: `4 passed`.
- The controlled rotation target `earnapp-proxy-w118904-ipv4-003` remains
  healthy with matching egress. No synthetic failure or rotation is allowed.
- Remaining release action: build/publish an immutable worker image containing
  the ownership guard, deploy worker-only with rollback evidence, then verify
  heartbeat/scheduler and repeated egress before the rotation gate.

## Copy/paste goal command

```text
Tiếp tục goal theo
docs/superpowers/plans/2026-09-19-earnapp-style-proxy-goal.md.

Giữ nguyên toàn bộ thay đổi hiện tại và dirty worktree. Không làm lại phần đã
xanh: durable EarnApp staged rotation, focused tests 87 passed, full suite
3379 passed/7 skipped, compileall passed. Không khôi phục boolean
`staged_verified` cũ.

Trước tiên hoàn tất artifact gate: kiểm tra kết quả build UI
`ghcr.io/assetforgeai-tech/cashpilot:earnapp-staged-20260919-lf`; xác minh
`/entrypoint.sh` của UI và worker dùng LF/shebang hợp lệ; smoke-test container
cô lập; chỉ deploy khi health ổn định 30-60 giây và có rollback digest. Giữ
nguyên `/data`, `/fleet`, compose overrides. Không lặp lại lỗi CRLF đã khiến
tini báo `exec /entrypoint.sh failed`.

Sau khi server/API khỏe, chỉ live-test Azure workers `118903` và `118904`;
tuyệt đối không dùng `test-sing`, `test-us`, `sing`, `eapp`. Thực hiện đúng một
controlled rotation trên `earnapp-proxy-w118904-ipv4-003` qua normal worker
API, không raw Docker, không bulk mutation. Thu bằng chứng old/new device ID,
proxy ID, egress, DNS/DoH, IPv6, UDP, direct fallback, watchdog, dashboard xóa
node cũ, DB lease/sticky ownership, retry/rollback và reboot persistence.

Chuẩn hóa fake-proxy cho provider dùng proxy theo EarnApp route: redsocks,
local DNS/DoH sau proxy readiness, iptables fail-closed, pin proxy endpoint,
verify egress, block IPv6/non-DNS UDP/direct fallback, parent watchdog. Chỉ
chia sẻ transport/readiness/watchdog. Không chia sẻ identity/account/token/link/
usage/allocator. EarnApp và Pawns giữ hai lane riêng; Pawns giữ `ip_used`;
EarnApp giữ account-scoped sticky ownership và serialized link queue. MYST/NKN
direct-only.

Rotation chỉ sau proxy failure xác nhận lặp lại: stop provider, teardown route,
lease bằng allocator đúng provider/account, dựng và verify route mới, start
provider, ghi evidence. Không rotate vì một probe đơn lẻ; không cross ownership.
Chỉ mở rộng provider-by-provider sau khi canary rotation đạt. Không tuyên bố
production-ready nếu thiếu packet-level live evidence.
```

## Short goal command

```text
Tiếp tục goal theo
docs/superpowers/plans/2026-09-19-earnapp-style-proxy-goal.md.

Giữ nguyên toàn bộ thay đổi hiện tại. Hoàn thiện EarnApp-style in-container
fake-proxy làm chuẩn network transport cho mọi provider dùng proxy: redsocks,
local DNS/DoH chỉ khởi động sau khi proxy route sẵn sàng, iptables fail-closed,
IPv6/UDP/direct fallback bị chặn, pin proxy IPv4, verify egress trước khi chạy
provider, watchdog tự khôi phục route. Sửa trước DoH startup/readiness cho
Ubuntu và macOS source runtimes.

Chỉ chia sẻ transport/readiness/watchdog. Không chia sẻ EarnApp identity,
account, token, link, usage, country hoặc allocator. Giữ EarnApp và Pawns là
hai lane riêng; Pawns giữ `ip_used`; EarnApp giữ sticky account ownership.
MYST/NKN direct-only.

Chạy local focused tests rồi full suite. Chỉ sau khi xanh mới canary một node
mỗi topology trên Azure workers `118903` và `118904`; không dùng `test-sing`,
`test-us`, `sing`, `eapp`. Thu bằng chứng packet-level cho egress, DNS/DoH,
IPv6, UDP, direct fallback, watchdog, rotation, reboot persistence; đối chiếu
provider dashboard trước khi mở rộng.

Rotation chỉ sau lỗi proxy xác nhận lặp lại: stop provider, teardown route cũ,
lease theo policy riêng, dựng route mới, verify egress/fail-closed, start
provider, ghi evidence. Không rotate vì một probe đơn lẻ. Không tuyên bố
production-ready nếu thiếu test hoặc live evidence; gặp credential/auth blocker
thì dừng tại blocker và báo rõ.
```

## Policy refresh — VN-only Proxy Pool (2026-09-20)

- Current Proxy Pool contains VN residential proxies only. EarnApp enables only `macos` and `ios`; Ubuntu is intentionally disabled until eligible non-VN residential inventory exists.
- Disposable rotation-17 respected this policy. Its authenticated workload verification returned `409` after account queue/link API calls succeeded, so it is evidence of a dashboard/workload gate still pending, not evidence to loosen OS/country policy.
- Cleanup completed through the normal API; the node returned to `PLANNED`, with no active proxy reservation. Worker reconciliation briefly lagged the DB after deletion and must be polled to a clean report before the next canary.

## Verification evidence refresh — 2026-09-20

- VN-only policy remains authoritative: EarnApp macOS/iOS only; Ubuntu disabled.
- Rotation-19 completed the disposable staged path with deterministic 3-sample failure, generation/device/proxy replacement, egress match, and normal API cleanup.
- `assume_account_side_effects=true` was explicit disposable-only orchestration evidence. Authenticated Earnings workload evidence is still open; do not mark goal complete.
- API 409 responses now include safe workload reason (`awaiting_metric_delta`, etc.) so operators can distinguish waitable earnings-cycle lag from auth/route failure.
