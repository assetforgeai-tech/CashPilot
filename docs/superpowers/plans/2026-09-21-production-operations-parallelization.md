# CashPilot Production Operations and Parallel Work Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` task-by-task. Every task owns an explicit file/resource scope and must attach evidence before completion.

**Goal:** Make CashPilot repeatably deployable on Azure, observable across tasks, safe to parallelize, clearer in the UI, and consistent in proxy-runtime behavior without mutating production until each gate passes.

**Architecture:** Keep the merged `main` release immutable. Add an operations control plane for resource inventory, SSH aliases, task ownership, evidence, and release manifests. Refine the shared network contract through provider-specific adapters; do not force EarnApp/Pawns/provider-specific lanes into one binary. Deploy through pinned GitHub/GHCR artifacts and an idempotent Azure bootstrap.

Proxy route safety and high-volume Proxy Pool scheduling are governed by the
follow-up addendum `docs/superpowers/plans/2026-09-23-proxy-route-and-pool-reliability-addendum.md`.
It is a mandatory pre-canary gate, not an optional optimization.

**Tech Stack:** Python/FastAPI, SQLite/CAS authority, Docker, shell startup scripts, Azure CLI, GitHub Actions, GHCR, PowerShell, pytest, Ruff.

## Global Constraints

- Canonical dirty repo `D:\1. WORK_true\CashPilot\repo` is read-only for these tasks; never reset, checkout, stash, or overwrite it.
- Work only from a fresh worktree based on `origin/main`; one task, one worktree, one owner.
- Forbidden live environments: `test-sing`, `test-us`, `sing`, `eapp`; production rollout requires a separate approval.
- No raw tokens, cookies, passwords, private keys, databases, runtime identity volumes, or provider responses in Git, docs, evidence, or PRs.
- Azure/VPS mutation requires a task-specific resource lock and a canary approval; read-only audits may run in parallel.
- Every completed task writes `docs/evidence/<task-id>-YYYY-MM-DD.md` and updates its Beads issue; only CP-001/export tooling rewrites `docs/ops/task-board.yaml`, preventing concurrent file conflicts.
- Beads is the authoritative task/claim store. `docs/ops/task-board.yaml` is a human-readable generated/exported view, never an independent task database.
- Every code task uses TDD, `pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `python -m compileall -q app tests`, and `git diff --check`.
- Runtime images/assets are referenced by immutable digest/SHA-256, never `latest`.
- Heartbeat is supervised at application, container, and host layers; a dead or frozen heartbeat must self-recover after task exit, process crash, container restart, and VPS reboot.
- No provider is production-ready while its direct/proxy topology, required ports, manual-access path, or dashboard-count acceptance is unknown.
- Destructive Azure cleanup requires a fresh approval after read-only inventory and reclamation dry-run.
- `proxybase-xyz` is included in production scope as provider 16. Its required
  input is only the secret `YOUR_PHRASE_WALLET` value; its collector is
  count-only. The official raw reference is
  `D:\\1. WORK_true\\CashPilot\\provider-runtime\\provider_code_setup_node\\proxybase.xyz.py`.
- Provider deployment targets the configured public IPv4 count `N` for every
  provider. Direct-only providers create `N` direct nodes. Hybrid providers
  create `N` direct plus `N` proxy nodes when at least `N` eligible proxies are
  available. Proxy-only providers create `N` proxy nodes when at least `N`
  eligible proxies are available. Insufficient proxy capacity must block the
  affected lane visibly; it must not silently reduce the requested count.
- Proxy Pool Probe is the only authority for upstream proxy liveness. Worker
  watchdogs enforce local fail-closed routing but never release leases or mark
  an upstream proxy dead. ACK and observed egress are apply/commit gates only.
- No provider can pass the fake-proxy gate until the addendum's bounded probe
  queue, durable failure state, deduplicated rotation queue, crash-loop guard,
  and packet-level evidence are complete for its applicable lane.

## Execution Graph

| Wave | Tasks that may run in parallel | Gate |
|---|---|---|
| 0 | CP-001 only | Operations files and ownership rules exist |
| 1 | CP-002, CP-003, CP-004, CP-005, CP-006, CP-007 | Each lane has isolated files/resources and evidence |
| 2 | CP-008, CP-009, CP-010 | Wave 1 contracts are stable |
| 3 | CP-014A, CP-014B, CP-014C, CP-014D, CP-014E, CP-014G, CP-014H | Worker-loss, authority, reliability, and provider-port contracts pass |
| 4 | CP-015A, then CP-015B | Proxy-route/state contracts and durable pool authority pass |
| 5 | CP-015C, CP-015D | Bounded probe/rotation queue and fake-proxy watchdog hardening pass |
| 6 | CP-015E | Fresh disposable scale/provider-group canary passes |
| 7 | CP-015F, CP-014I, CP-014K | New release/rollback gate, Cloud Shell, and ProxyBase.xyz gates pass |
| 8 | CP-011, CP-012 | Fresh canary/release evidence for the changed runtime passes; closed historical issues remain immutable |
| 9 | CP-014J | Fresh destructive approval and recreate acceptance |
| 10 | CP-013 | Separate production approval |

Do not start a task whose dependency gate is incomplete. Tasks in the same wave must not edit each other's owned files.

### Cross-cutting policy: heartbeat-timeout worker loss

Worker heartbeat is the authoritative detector for a VPS that is unreachable,
but one missed heartbeat is not enough to release leases. The control plane
must use this sequence:

1. `OFFLINE`: heartbeat stale for `STALE_WORKER_SECONDS` (currently 3 minutes);
   no lease mutation.
2. `LEASE_RECLAIM_DUE`: no heartbeat for 15 minutes. Heartbeat time is the only
   liveness authority; do not add ping, ICMP, SSH, TCP, Azure, or client probes.
3. At 15 minutes, release every **runtime proxy lease** belonging to that
   worker across all proxy-capable providers, idempotently and with an audit
   reason `WORKER_HEARTBEAT_STALE_15M`.
4. Preserve provider/account egress ownership. Releasing a runtime lease must
   not make a sticky EarnApp/account egress reusable while that account remains
   in its pool.
5. Direct-only lanes have no proxy lease and are only marked unavailable.
6. If the worker returns, do not silently reattach old leases; redeploy or
   reacquire through normal provider policy and CAS.

This policy must never release leases after a single missed heartbeat or a
control-plane read failure. Recovery hold, account ownership, and
provider-specific Pawns/EarnApp rules remain separate.

---

### Task CP-001: Operations inventory, task board, and locks

**Owner:** control-plane/documentation task

**Files:**
- Create: `docs/ops/resource-inventory.yaml`
- Create: `docs/ops/task-board.yaml`
- Create: `tools/export-task-board.py`
- Create: `docs/ops/ssh-aliases.example`
- Create: `docs/ops/README.md`
- Test: `tests/test_ops_contract.py`

**Produces:** initialized Beads task store plus a generated human-readable view; schema for VPS/provider/proxy/runtime ownership; task ID, owner, path scope, resource lock, dependency, acceptance criteria, evidence path, status; no secrets.

**Steps:**
- Run `C:\Users\KALINH\AppData\Local\Microsoft\WinGet\Links\bd.exe init` in the dedicated CP-001 worktree; do not initialize Beads in any dirty historical worktree.
- Create CP-001 through CP-013 as Beads issues with dependencies matching the execution graph.
- Write tests rejecting plaintext secret fields and overlapping mutable scopes.
- Implement a small YAML loader/validator used by tests and CI.
- Implement `tools/export-task-board.py` to export the claimed owner/status/scope from Beads into `docs/ops/task-board.yaml`.
- Add `resource-inventory.yaml` entries using secret file references only.
- Verify duplicate `path_scope` or `resource_lock` is rejected unless explicitly read-only.
- Commit `docs: add operations inventory and task ownership contracts`.

**Acceptance:** `bd ready` exposes only dependency-ready work, atomic `bd update <id> --claim` prevents duplicate ownership, and a new task can discover the VPS credential file, SSH alias, owner, lock, and evidence location without receiving credentials in chat.

---

### Task CP-002: SSH/Azure worker access wrapper

**Owner:** infrastructure task

**Files:**
- Create: `tools/ssh-worker.ps1`
- Create: `tools/azure-worker-preflight.ps1`
- Modify: `docs/ops/ssh-aliases.example`
- Test: `tests/test_ssh_worker_tools.py`

**Consumes:** CP-001 inventory schema.

**Produces:** idempotent PowerShell commands for `az vm show`, public-IP lookup, port-22 preflight, SSH key selection, and non-interactive `ssh -o BatchMode=yes`.

**Rules:** Never embed passwords or private-key contents; accept only a path from the inventory/secret store. Fail before SSH if VM is not running or IP is missing.

**Acceptance:** `./tools/azure-worker-preflight.ps1 -WorkerId <id>` returns structured JSON; SSH wrapper reaches the selected worker or fails with an actionable reason.

---

### Task CP-003: Shared proxy-network contract audit

**Owner:** network-contract task

**Files:**
- Modify: `app/provider_network_audit.py`
- Modify: `app/provider_modes.py`
- Modify: `app/provider_runtime.py`
- Test: `tests/test_provider_network_contracts.py`
- Test: `tests/test_provider_network_matrix.py`

**Produces:** provider capability matrix for `direct`, `proxy`, `direct+proxy`, DNS/DoH, IPv6, UDP, direct-fallback, watchdog, and restart behavior.

**Rules:** Shared contract validates fail-closed egress; adapters retain provider-specific behavior. EarnApp and Pawns remain separate policy lanes where required.

**Acceptance:** Unsupported capabilities are rejected before deploy; every provider has an explicit mode instead of an implicit fallback.

---

### Task CP-004: Provider fake-proxy audit and canary matrix

**Owner:** provider-network read/repair task

**Files:**
- Modify only provider-owned runtime/config files selected from the matrix.
- Tests: provider-specific tests under `tests/`.
- Evidence: `docs/evidence/CP-004-*.md`.

**Consumes:** CP-003 matrix.

**Produces:** per-provider proof of egress IP, DNS, IPv6, UDP, TLS, and direct-fallback behavior.

**Rules:** One provider group per isolated branch/worktree. No broad renderer rewrite. No production node mutation. Packet capture is required for claims of zero leak.

**Acceptance:** Each provider group is `PASS`, `FAIL`, or `INCONCLUSIVE` with exact reason and rollback reference; no unsupported provider is marked passed.

---

### Task CP-005: UI information architecture and status vocabulary

**Owner:** frontend task

**Files:**
- Modify: `app/static/js/app.js`
- Modify: `app/static/css/style.css`
- Modify: relevant route/templates in `app/main.py` only when required by existing API contracts
- Tests: `tests/test_frontend_wiring.py`, new focused UI tests
- Evidence: `docs/evidence/CP-005-ui-sweep-*.md`

**Produces:** clear sections for Overview, Workers/VPS, Provider Accounts, Proxy Pool, Runtime, Nodes, Collectors/Payments, Recovery/Alerts, Settings, Audit.

**Rules:** No `window.prompt`; destructive operations require modal confirmation; statuses use `healthy`, `degraded`, `offline`, `blocked`, `unknown`; API errors and loading states are visible.

**Acceptance:** Existing endpoints remain compatible; every action has validation, pending, success, and failure states; screenshots/evidence cover each menu and critical button.

---

### Task CP-006: Runtime distribution manifest and GHCR/GitHub release contract

**Owner:** release/runtime task

**Files:**
- Create: `release/runtime-manifest.schema.json`
- Create: `tools/verify-runtime-manifest.py`
- Modify: `.github/workflows/release.yml`
- Modify: `Dockerfile`, `Dockerfile.worker` only if required for immutable labels
- Tests: `tests/test_runtime_manifest.py`, `tests/test_compose_image_pins.py`
- Docs: `docs/earnapp-private-runtime.md` and `docs/ops/README.md`

**Produces:** signed/checksummed manifest mapping release to GitHub asset/GHCR digest, architecture, provider, and rollback version.

**Rules:** GitHub Releases distribute scripts/manifests; GHCR distributes container images. Workers pull by digest, verify SHA-256/signature, cache locally, and fail closed on mismatch. Credentials enter via runtime secret injection, never the repository.

**Acceptance:** A fresh worker can verify and pull a pinned artifact without contacting CashPilot for bulk binary bytes; failed verification leaves the previous artifact active.

---

### Task CP-007: Azure CLI VM and startup bootstrap

**Owner:** Azure provisioning task

**Files:**
- Modify: `azure_create/worker-startup.sh`
- Create: `azure_create/create-worker.ps1`
- Create: `azure_create/create-worker.sh`
- Tests: `tests/test_azure_worker_startup.py`, new CLI contract tests
- Docs: `docs/ops/azure-runbook.md`

**Produces:** raw Azure CLI command generator supporting subscription, region, VM size/image, OS disk, public IPv4 count, NSG policy, labels, startup-script version, dry-run, and post-create verification.

**Rules:** Do not commit actual Azure password/token. Password mode is optional and emits a warning; SSH key mode is default. Open only ports required by the provider matrix; “full TCP+UDP” requires explicit per-task approval and an evidence record.

**Acceptance:** Dry-run is deterministic; startup is idempotent; worker enrollment survives reboot; public IP inventory reconciles with Azure API.

---

### Task CP-008: Account/token/collector operational policy

**Owner:** account lifecycle task

**Files:**
- Modify: `app/earnapp_collection.py`, `app/earnapp_lifecycle.py`, `app/earnapp_accounts.py`
- Tests: existing EarnApp lifecycle/account/queue tests plus focused expiry tests
- Evidence: `docs/evidence/CP-008-*.md`

**Consumes:** CP-001 task locks; does not modify frontend or provider network files.

**Produces:** token-expiry detection, serialized account operations, explicit suspended/locked handling, collector freshness, and dashboard alert state.

**Acceptance:** Expired token never causes account deletion; link retries are serialized per account; provider/account state is distinguished from node offline/banned state.

---

### Task CP-009: Lease/release/heartbeat and capacity reconciliation

**Owner:** authority/database task

**Files:**
- Modify: `app/database.py`
- Modify: `app/provider_topology.py`
- Modify: `app/provider_automation.py`
- Tests: lease, topology, lifecycle, and reconciliation tests
- Evidence: `docs/evidence/CP-009-*.md`

**Produces:** authoritative lease/ownership reconciliation, grouped heartbeat, sticky egress ownership policy, provider-specific rotation rules, and concise used/available capacity counters.

**Acceptance:** Reconciliation is idempotent; shared-proxy groups heartbeat once; EarnApp/Pawns lane rules remain isolated; dashboard counts match database authority.

### Task CP-014A: Unified worker-loss policy contract

**Owner:** worker-liveness task

**Depends on:** CP-001 only.

**Files:**
- Create: `app/worker_resource_policy.py`
- Test: `tests/test_worker_resource_policy.py`
- Evidence: `docs/evidence/CP-014A-YYYY-MM-DD.md`

**Produces:** a pure decision contract that consumes only last heartbeat and
current time. It returns `ONLINE`, `OFFLINE`, or `RECLAIM_ALL_WORKER_RESOURCES`
plus the exact resource families to reclaim.

**Rules:** heartbeat is the only liveness signal. At 3 minutes without a
heartbeat return `OFFLINE`; at 15 minutes return
`RECLAIM_ALL_WORKER_RESOURCES`. Reclaim worker-scoped runtime proxy leases,
NKN wallet leases, Mysterium wallet leases, provider-instance runtime
assignments, and worker capacity reservations. Preserve provider credentials,
account-pool membership, EarnApp account/egress sticky ownership, PayPal
ownership, and historical evidence. Do not add another liveness signal or
client code.

**Acceptance:** deterministic tests cover heartbeat recovery, exact 3-minute
and 15-minute boundaries, missing/invalid timestamps, clock skew, and duplicate
scheduler evaluation.

### Task CP-014B: Worker-resource authority inventory

**Owner:** resource-contract task

**Depends on:** CP-001 only.

**Files:**
- Create: `app/worker_resource_registry.py`
- Test: `tests/test_worker_resource_registry.py`
- Evidence: `docs/evidence/CP-014B-YYYY-MM-DD.md`

**Produces:** one registry enumerating every worker-bound authority table,
release function, release reason, preserved ownership table, and post-release
state. This prevents a new provider lease type from being silently omitted.

**Acceptance:** tests fail if proxy leases, NKN wallets, Myst wallets,
provider-instance assignments, or capacity reservations lack an explicit
reclaim/preserve decision. Direct-only runtime rows are retired but have no
proxy lease to release.

### Task CP-014C: Atomic worker-resource reclamation

**Owner:** lease-authority task

**Depends on:** CP-009 merged; consumes the CP-014B registry contract.

**Files:**
- Modify: `app/database.py`
- Test: `tests/test_worker_resource_reclamation.py`
- Evidence: `docs/evidence/CP-014C-YYYY-MM-DD.md`

**Produces:** `reclaim_worker_resources(worker_id, reason, reclamation_token)`
as one idempotent transaction covering every worker-scoped authority row.

**Rules:** release proxy runtime leases, NKN/Myst wallet leases, runtime
assignments, and capacity reservations. Preserve sticky egress ownership,
EarnApp account ownership, account-pool membership, PayPal ownership, proxy
health, credentials, and history. Mark the worker resource generation revoked
so a late heartbeat cannot resurrect reclaimed authority. Replaying the same
reclamation token changes nothing.

**Acceptance:** tests prove every registered resource family is reclaimed once,
preserved ownership survives, capacity updates atomically, a new worker can
acquire released resources, and the old worker generation cannot reclaim them.

### Task CP-014D: Heartbeat scheduler and old-worker fencing

**Owner:** scheduler integration task

**Depends on:** CP-014A and CP-014C merged.

**Files:**
- Modify: `app/main.py` (`_check_stale_workers` integration only)
- Test: `tests/test_worker_offline_lease_reclamation.py`
- Evidence: `docs/evidence/CP-014D-YYYY-MM-DD.md`

**Produces:** the single system-wide worker-loss scheduler. Existing separate
NKN/EarnApp/Myst stale-worker reclaim calls are removed or delegated to the one
CP-014C transaction. Heartbeats from a reclaimed worker generation are
accepted only as quarantined/re-enrollment evidence, never as authority to
restore old resources.

**Rules:** no new client heartbeat and no client-side lease decision. Persist
the confirmation/audit token before release. Do not delete the enrolled worker
row. A returning worker must obtain fresh leases through the normal CAS path.

**Acceptance:** 3-minute stale marks worker offline without releasing leases;
15-minute stale releases all runtime proxy leases exactly once.

### Task CP-014E: Worker-loss dashboard and audit visibility

**Owner:** frontend/status task

**Depends on:** CP-014D API/status contract merged.

**Files:**
- Modify: `app/static/js/app.js`
- Modify: `app/templates/fleet.html`
- Test: `tests/test_frontend_wiring.py`
- Evidence: `docs/evidence/CP-014E-YYYY-MM-DD.md`

**Produces:** concise worker status showing heartbeat age, `offline` at three
minutes, resource reclaim countdown, reclaimed resource counts, fencing state,
and the requirement for fresh allocation on return.

### Task CP-014F: Disposable worker-loss canary

**Owner:** canary/evidence task

**Depends on:** CP-014D and CP-014E merged and explicit disposable-resource approval.

**Files:**
- Create: `docs/evidence/CP-014F-YYYY-MM-DD.md`
- Create: `docs/evidence/CP-014F-result.json`

**Resources:** one disposable worker only. No production resource.

**Checks:** stop heartbeat; verify worker becomes offline after 3 minutes with
resources retained. Keep heartbeat absent through 15 minutes; verify proxy
leases, NKN/Myst wallets, runtime assignments, and capacity reservations are
reclaimed together; preserved ownership remains; dashboard reconciles; the old
worker is fenced; a new worker can acquire released resources; cleanup passes.

**Acceptance:** machine-readable before/after lease inventory and cleanup PASS.

---

### Task CP-014G: Heartbeat supervision and reboot persistence

**Owner:** worker reliability task

**Depends on:** CP-014A and CP-014D.

**Files:**
- Modify: `app/worker_api.py` (heartbeat supervisor only)
- Modify: `Dockerfile.worker` and `docker-compose.fleet.yml` (healthcheck/restart only)
- Modify: `azure_create/worker-startup.sh` (systemd supervision only)
- Test: `tests/test_worker_heartbeat_supervisor.py`
- Test: `tests/test_bootstrap_contract.py`
- Evidence: `docs/evidence/CP-014G-YYYY-MM-DD.md`

**Produces:** one bounded supervisor that recreates a finished heartbeat task;
heartbeat-aware health detects a frozen task; Docker/systemd restart after
process failure and boot. Shutdown cancellation remains clean.

**Rules:** one heartbeat task; no duplicate loops; bounded backoff; health
proves recent server contact, not merely TCP/API process liveness; worker API
remains private. Preserve the 3-minute offline and 15-minute reclaim policy.

**Acceptance:** tests cover task exception, unexpected completion, frozen
heartbeat, container exit, reboot, duplicate-supervisor prevention, and clean
shutdown. Disposable canary proves recovery without manual restart.

### Task CP-014H: Complete provider port and access matrix

**Owner:** provider-network/access task

**Depends on:** CP-003.

**Files:**
- Create: `docs/ops/provider-port-matrix.yaml`
- Modify: `app/provider_runtime.py` only for evidenced catalog corrections
- Test: `tests/test_provider_port_matrix.py`
- Evidence: `docs/evidence/CP-014H-YYYY-MM-DD.md`

**Produces:** explicit matrix for all providers and lanes: direct-only,
direct+proxy, proxy-only; public IPv4 slot use; inbound TCP/UDP; outbound
requirements; host network/TUN/capabilities; watchdog; operator access.

**Required topology:** Mysterium/NKN direct-only; EarnFM, ProxyBase,
ProxyBase.xyz, ProxyRack, Repocket, Spide, TraffMonetizer, URNetwork hybrid;
EarnApp, IPRoyal Pawns, PacketStream, Proxies.sx, UpRock, Wipter proxy-only.

**Count contract:** for `N=20`, every direct-only provider gets 20 direct
nodes; every hybrid provider gets 20 direct plus 20 proxy nodes; every
proxy-only provider gets 20 proxy nodes. Proxy lanes require 20 eligible proxy
assignments. Mysterium must expose UDP `56000-56100` as the authoritative
runtime/NSG range.

**ProxyBase.xyz contract:** normalize the existing host-systemd runtime against
the raw reference, preserving the official CLI wallet import/login/seller
flow. Do not add unsupported account fields. Input is one secret phrase only;
collector reports node count only. Keep wallet state in its protected runtime
volume and never expose the phrase or wallet/password material in evidence.

**Access requirements:** every Myst/Wipter/UpRock node gets a controlled
tunnel/noVNC path to this PC. Every NKN node automatically exposes its native
web view at `http://<node-public-ip>:30000/web`; its username/password are read
from that node's wallet and password files and delivered through a secret-safe
operator channel. Access must not expose wallet contents in Git, evidence, or
general API responses.

**Acceptance:** no implicit mode or missing port decision; unknowns are
`INCONCLUSIVE`, never guessed open ports. Matrix drives NSG/startup tests.

### Task CP-014I: Self-contained Azure Cloud Shell deployment script

**Owner:** Azure bootstrap task

**Depends on:** CP-002, CP-006, CP-007, CP-014H.

**Files:**
- Create: `azure_create/cloud-shell-create-worker.sh`
- Create: `tests/test_cloud_shell_create_worker.py`
- Modify: `docs/ops/azure-runbook.md`
- Evidence: `docs/evidence/CP-014I-YYYY-MM-DD.md`

**Produces:** one pasteable raw Azure CLI script with variables for
subscription, fixed region, VM size `Standard_D8s_v4`, Ubuntu 24.04 x64, OS
disk `P20`/512 GiB, configurable public IPv4 count (initially 20), exact NSG
ports from CP-014H, embedded cloud-init/startup, immutable runtime digest,
worker enrollment, and post-create reconciliation.

**Rules:** no local-file reads; secrets are runtime variables/prompts and never
committed or logged. Static public IPs, deterministic NIC/IP names, dry-run,
idempotency, and pre-mutation inventory are mandatory. Full TCP+UDP requires
explicit matrix proof.

**Acceptance:** shell/static tests prove no local-path dependency, deterministic
20-IP topology, least-privilege NSG, and reboot-persistent enrollment.

### Task CP-014J: Cleanup, reclaim, and operator acceptance gate

**Owner:** release-operations task

**Depends on:** CP-014C, CP-014D, CP-014G, CP-014H, CP-014I, CP-011, CP-012.

**Files:**
- Create: `docs/ops/azure-cleanup-runbook.md`
- Create: `docs/evidence/CP-014J-YYYY-MM-DD.md`
- Create: `tools/azure-inventory-and-cleanup.sh` (dry-run default)
- Test: `tests/test_azure_cleanup_contract.py`

**Sequence:** read-only Azure inventory; export worker/proxy/wallet/runtime
ownership; reclamation dry-run; fresh explicit approval; delete only listed
old/disposable VPS resource groups and dependent NIC/PIP/disk/NSG resources;
verify no worker-bound leases; create one East Asia worker; deploy; stop and
report for manual provider-dashboard checks. Preserve account pools,
credentials, sticky egress, and earnings/history.

**Acceptance:** machine-readable before/after inventory, zero orphaned
worker-bound resources, no out-of-scope deletions, operator sign-off before
repeat cleanup.

### Task CP-014K: ProxyBase.xyz runtime and count-only collector normalization

**Owner:** ProxyBase.xyz provider task

**Depends on:** CP-003 and CP-014H.

**Files:**
- Reference: `D:\\1. WORK_true\\CashPilot\\provider-runtime\\provider_code_setup_node\\proxybase.xyz.py`
- Modify: `app/provider_runtime.py`, `app/provider_installers.py`,
  `app/orchestrator.py`, and the ProxyBase.xyz service contract only where
  the audit proves drift
- Modify/create: the ProxyBase.xyz collector adapter and focused tests
- Evidence: `docs/evidence/CP-014K-YYYY-MM-DD.md`

**Required behavior:** input has exactly one secret field, the wallet phrase
(`YOUR_PHRASE_WALLET` at raw-code placeholder level). Runtime performs the
official CLI wallet import, login, and seller start flow. Collector is
count-only; it must not claim earnings or invent an API balance.

**Audit gates:** reconcile the raw host-systemd reference with the current
container/image path; remove duplicate foreground/systemd starts; preserve
wallet state in the protected runtime volume; pin the installer/image instead
of `latest`; verify restart/reboot behavior and one node per requested IPv4
slot. Any difference between raw code and current runtime requires a focused
regression test and evidence.

**Acceptance:** 20 requested slots yield 20 ProxyBase.xyz nodes when the
provider's direct/proxy lane prerequisites are met; phrase is never logged or
returned; collector reports only node count; runtime survives restart/reboot;
no duplicate seller processes exist.

### Task CP-010: Security and operations audit sweep

**Owner:** read-only audit task

**Files:** no production changes initially.

**Outputs:** `docs/evidence/CP-010-security.md`, `docs/evidence/CP-010-ui-ops.md`.

**Scope:** secret boundaries, auth/runtime asset binding, path/shell injection, Docker capability/mounts, UI destructive actions, Azure NSG exposure, GitHub/GHCR permissions, and rollback.

**Acceptance:** Findings are severity-ranked with exact file/line/resource evidence; fixes become separate scoped tasks, not opportunistic edits.

---

### Task CP-011: Disposable Azure canary

**Owner:** release validation task

**Depends on:** CP-002 through CP-010 required contracts and CI, plus the new
CP-015A through CP-015F proxy-route/pool reliability gates. Historical CP-011
evidence remains immutable; this dependency requires a fresh follow-up canary.

**Resources:** only an explicitly approved disposable Azure worker; no production workers or forbidden environments.

**Checks:** bootstrap, artifact verification, worker heartbeat, provider deployment, proxy egress/DNS/IPv6/UDP, watchdog fault injection, reboot persistence, collector/payment reconciliation, cleanup convergence.

**Acceptance:** All gates have machine-readable evidence; failed gate stops rollout and preserves previous runtime. No production mutation.

---

### Task CP-012: Release candidate and rollback package

**Owner:** release manager task

**Files:**
- Create: `docs/ops/release-checklist.md`
- Create: `docs/evidence/CP-012-release-candidate.md`
- Tag only after explicit approval.

**Depends on:** CP-015F when the release contains route/pool changes.

**Produces:** release tag, manifest, checksums, rollback command, change summary, known limitations, and canary evidence index.

**Acceptance:** A fresh operator can deploy and roll back without chat history; production rollout remains disabled until separate approval.

---

### Task CP-013: Production rollout

**Owner:** operator task, separate approval required

**Depends on:** CP-011, CP-012, and CP-015F. CP-015F is a planned follow-up
gate; it does not reopen closed CP-011/CP-012 issues.

**Stages:** one worker -> one provider group -> one region -> remaining fleet. A
full-worker diagnostic round traverses provider lanes **sequentially**; it is
not a concurrent launch of all providers. Keep the provider's direct/proxy
cardinality, EarnApp account queue, Pawns private allocator, NKN/Myst wallet
ownership, and fail-closed network gates. Catalog filename order is only the
current implementation order, not an approved provider rollout priority.

**Diagnostic-round contract (pre-live gate):**

1. Freeze the worker ID, release digest, public-IPv4 slot manifest, intended
   provider/lane order, eligible proxy capacity, and existing node/identity,
   wallet, volume, account, and lease inventory. Mark non-automatable providers
   explicitly; never count them as successful automatic deployments.
2. Start one durable round ID for one worker and an operator-selected positive
   generation. Persist intended provider rows **before** dispatch. On each
   sequential provider/slot result, persist only redacted status/count/identity
   labels. Separate `started` (CashPilot worker acknowledgement) from external
   provider online/traffic/earnings proof; preserve `pending`, `failed`,
   `inconclusive`, and excluded-lane reasons. A crash leaves an incomplete round
   visible and must not start another attempt on heartbeat or restart.
3. Continue through ordinary provider failures to collect the entire round's
   errors. Stop dispatch immediately if the ledger fails, a proxy route can
   fall back to direct egress, a wrong wallet/identity/lease could be touched,
   or another data-loss/security invariant fails. Do not patch code or rotate,
   delete, or clean nodes mid-round.
4. After the final provider, freeze the run ledger and gather worker logs,
   network/egress/DNS evidence, CashPilot counts, external provider dashboard
   observations, traffic, collectors, and lease/wallet reconciliation under
   the same round ID. Group errors by root cause; use isolated code/test PRs
   in parallel only when file and resource ownership do not overlap. Integrate
   fixes through green CI and a pinned release with rollback.
5. Only after fixes and backup/inventory, clean the **approved** worker's
   provider runtimes in dependency order. Preserve identity volumes, accounts,
   sticky ownership, wallets, and leases unless an exact policy and separate
   scoped approval explicitly permit release. Verify before/after state and
   rollback. Advance the generation only after this gate, then repeat one
   diagnostic round. Never run two rounds or a clean on the same worker at once.

**Automatic-retry gate:** a heartbeat may claim at most one round per worker
and generation in SQLite. Failed or pending targets are not dispatched again
by later heartbeats or UI restarts. Changing generation is an explicit
operator action through `cashpilot_autodeploy_round_generation`; it is not an
implicit retry. `cashpilot_autodeploy_worker_ids` must contain exactly the
approved worker ID, and the worker key must be confirmed. Missing, malformed,
duplicate, or multi-worker scope fails closed. No round status, including
`completed`, is evidence of provider earnings or production readiness.

**Live entry:** first prove durable redacted round records, duplicate-heartbeat
and restart suppression, failure continuation, and ledger-failure stop using
synthetic tests. Then merge code/evidence with green CI, verify current
control-plane/worker release compatibility and backup/rollback, and obtain an
exact worker/provider/resource approval. Keep global auto-deploy disabled
until that gate. Initial live stage remains one approved canary slot; a
full-worker round requires its own approval and is not inferred from it.

**Acceptance:** run IDs reconcile desired/attempted/started/failed/pending
counts; provider dashboards, CashPilot state, collectors, payments, leases,
network evidence, and manual operator observations reconcile after each stage.

**Implementation checkpoint (2026-09-26):** The synthetic ledger currently
records provider-lane intent/outcomes and blocks *heartbeat auto-deploy* retries
for the same worker/generation. An interrupted `running` round remains visible
and fences both the same generation and higher generations until operator
reconciliation; it is never retried implicitly after restart. It does not yet
freeze per-slot intent, a release/IPv4/proxy/identity snapshot, external
provider proof, or an approved provider ordering. Existing EarnApp lifecycle
and proxy-pool recovery remain separate policies; this gate must not silently
disable them. Before live entry, add a provider/slot reconciliation view,
classify fatal network/identity/lease violations versus ordinary failures, and
explicitly exclude unsupported/manual provider lanes. Do not infer that the
present generic sequence covers every provider or that a green synthetic test
authorizes a live worker.

The diagnostic dispatcher now propagates the generic deploy response into the
round ledger: `pending_capacity`, blocked/inconclusive, failed, empty, and
malformed responses are not reported as `started`. A `started` outcome requires
an explicit deployed/running response with instance or running evidence. This
is status accounting only; it does not replace slot-level reconciliation or
external provider proof.

---

## Task Prompt Templates

Use one fresh worktree per task. Replace only `<TASK_ID>`, `<WORKTREE>`, and `<SCOPE>`:

```text
Work only on <TASK_ID> in <WORKTREE>. You are not alone in the repository.
Own only <SCOPE>; do not edit another task's files, VPS, provider, branch, or
runtime asset. Read AGENTS.md. Use TDD. Do not use production or forbidden
workers. Before completion run the task tests, uv run ruff check ., uv run ruff
format --check ., python -m compileall -q app tests, and git diff --check.
Write docs/evidence/<TASK_ID>-YYYY-MM-DD.md with commands, results, failures,
rollback reference, and remaining risks. Update docs/ops/task-board.yaml.
Stop on missing credentials or ambiguous provider behavior; report the exact
blocker instead of guessing.
```

## Parallel Dispatch Recommendation

- Start CP-001 first and finish it before any mutation task.
- Then dispatch CP-002, CP-003, CP-005, CP-006, CP-007, and CP-010 in parallel.
- Dispatch CP-004 only after CP-003 publishes the matrix; split CP-004 by provider group if each group has a separate worktree.
- Dispatch CP-008 and CP-009 in parallel only because they own separate files and share no migration.
- Dispatch CP-014A and CP-014B in parallel; both create isolated modules/tests.
- CP-014C starts after CP-014B and CP-009 merge; it exclusively owns the DB
  reclamation transaction.
- CP-014D starts after CP-014A and CP-014C merge; it exclusively owns
  `_check_stale_workers` and heartbeat fencing integration.
- CP-014E starts after CP-014D publishes its status contract.
- CP-014F runs last with explicit disposable-resource approval.
- CP-014G and CP-014H may run in parallel after CP-014A/CP-003 contracts;
  neither may mutate Azure or provider production resources.
- CP-014I starts only after CP-014H freezes the port matrix and CP-007/CP-006
  release contracts are merged.
- CP-014K starts after CP-014H; it may run in parallel with CP-014I because it
  owns only the ProxyBase.xyz runtime/collector lane.
- CP-014J is destructive and strictly serial: inventory -> dry-run -> fresh
  approval -> cleanup -> one-worker deployment -> operator dashboard check.
- Run CP-011 and CP-012 serially after all required gates.
- Never run CP-007 and CP-011 against the same VPS concurrently.
- Never run two tasks that mutate the same provider/account/proxy lease group concurrently.

## Completion Rule

The project is production-ready only when CP-001 through CP-012, CP-014A
through CP-014K, and CP-015A through CP-015F have evidence-backed PASS status.
CP-013 requires a separate explicit production rollout approval.
