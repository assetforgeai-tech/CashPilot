# CashPilot Production Operations and Parallel Work Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` task-by-task. Every task owns an explicit file/resource scope and must attach evidence before completion.

**Goal:** Make CashPilot repeatably deployable on Azure, observable across tasks, safe to parallelize, clearer in the UI, and consistent in proxy-runtime behavior without mutating production until each gate passes.

**Architecture:** Keep the merged `main` release immutable. Add an operations control plane for resource inventory, SSH aliases, task ownership, evidence, and release manifests. Refine the shared network contract through provider-specific adapters; do not force EarnApp/Pawns/provider-specific lanes into one binary. Deploy through pinned GitHub/GHCR artifacts and an idempotent Azure bootstrap.

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

## Execution Graph

| Wave | Tasks that may run in parallel | Gate |
|---|---|---|
| 0 | CP-001 only | Operations files and ownership rules exist |
| 1 | CP-002, CP-003, CP-004, CP-005, CP-006, CP-007 | Each lane has isolated files/resources and evidence |
| 2 | CP-008, CP-009, CP-010 | Wave 1 contracts are stable |
| 3 | CP-011, CP-012 | Release artifacts and canary gates pass |
| 4 | CP-013 | Separate production approval |

Do not start a task whose dependency gate is incomplete. Tasks in the same wave must not edit each other's owned files.

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

---

### Task CP-010: Security and operations audit sweep

**Owner:** read-only audit task

**Files:** no production changes initially.

**Outputs:** `docs/evidence/CP-010-security.md`, `docs/evidence/CP-010-ui-ops.md`.

**Scope:** secret boundaries, auth/runtime asset binding, path/shell injection, Docker capability/mounts, UI destructive actions, Azure NSG exposure, GitHub/GHCR permissions, and rollback.

**Acceptance:** Findings are severity-ranked with exact file/line/resource evidence; fixes become separate scoped tasks, not opportunistic edits.

---

### Task CP-011: Disposable Azure canary

**Owner:** release validation task

**Depends on:** CP-002 through CP-010 required contracts and CI.

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

**Produces:** release tag, manifest, checksums, rollback command, change summary, known limitations, and canary evidence index.

**Acceptance:** A fresh operator can deploy and roll back without chat history; production rollout remains disabled until separate approval.

---

### Task CP-013: Production rollout

**Owner:** operator task, separate approval required

**Depends on:** CP-011 and CP-012.

**Stages:** one worker -> one provider group -> one region -> remaining fleet, with pause gates and automatic rollback on health failure.

**Acceptance:** provider dashboards, CashPilot state, collectors, payments, leases, and network evidence reconcile after each stage.

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
- Run CP-011 and CP-012 serially after all required gates.
- Never run CP-007 and CP-011 against the same VPS concurrently.
- Never run two tasks that mutate the same provider/account/proxy lease group concurrently.

## Completion Rule

The project is production-ready only when CP-001 through CP-012 have evidence-backed PASS status. CP-013 requires a separate explicit production rollout approval.
