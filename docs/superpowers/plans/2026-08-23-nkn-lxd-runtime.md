# NKN LXD Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run every new NKN direct slot in its own resource-limited LXD instance, with CPU and RAM controlled authoritatively from CashPilot server Settings.

**Architecture:** The server validates `nkn_lxd_cpu` and `nkn_lxd_memory_mib` and includes them in every slot assignment. The worker uses an NKN-only Unix-socket client to a root host helper; that helper can manage only `cashpilot-nkn-*` LXD instances and executes the official NKN Docker image inside each instance. Legacy Docker NKN state remains readable for rollback, while all new assignments select LXD.

**Tech Stack:** FastAPI/Pydantic, Python stdlib Unix HTTP, LXD/LXC, Docker inside LXD, pytest, Bash/systemd.

## Global Constraints

- Modify only NKN-specific runtime, worker, Settings, bootstrap/helper, tests, release wiring, and NKN documentation.
- Do not modify or redeploy protected providers.
- Keep the test-sing Docker NKN baseline stopped and preserve its identity, volume, wallet ID `1`, and assignment version `3` during canary adoption.
- CPU/RAM Settings affect future creation/recreation only; a Settings save never silently resizes running LXD instances.
- Do not use Azure CLI.

---

### Task 1: Server-authoritative resource settings

**Files:**
- Modify: `app/main.py`
- Modify: `app/templates/settings.html`
- Test: `tests/test_nkn_lxd_settings.py`
- Test: `tests/test_nkn_auto_deploy.py`

**Interfaces:**
- Produces: `_nkn_lxd_settings(config: Mapping[str, Any]) -> dict[str, int]`
- Produces deploy payload fields: `runtime_backend`, `lxd_cpu`, `lxd_memory_mib`

- [ ] Write tests for defaults `1 CPU / 1024 MiB`, bounds, API validation, UI fields, and payload propagation.
- [ ] Run the focused tests and confirm they fail because the settings contract does not exist.
- [ ] Implement validation, Settings fields/help text, and payload propagation.
- [ ] Re-run the focused tests and confirm they pass.

### Task 2: NKN-only LXD worker client and lifecycle dispatch

**Files:**
- Create: `app/nkn_lxd_runtime.py`
- Modify: `app/nkn_runtime.py`
- Modify: `app/worker_api.py`
- Modify: `Dockerfile.worker`
- Test: `tests/test_nkn_lxd_runtime.py`
- Test: `tests/test_worker_nkn_deploy.py`
- Test: `tests/test_worker_nkn_sync.py`

**Interfaces:**
- Produces: `deploy_slot`, `suspend_slot`, `resume_slot`, `remove_slot`, and `node_evidence` over `/run/cashpilot-nkn-agent.sock`.
- Consumes: exact wallet-assignment CAS tuple and server resource settings.

- [ ] Write tests for LXD deploy dispatch, secret redaction, evidence, lease guard, ACK resume, and rejected-assignment cleanup.
- [ ] Run the focused tests and confirm missing LXD behavior fails.
- [ ] Implement the minimal Unix-socket client and backend dispatch while preserving legacy Docker state handling.
- [ ] Restore the manual tested four-key NKN `config.json` now that LXD provides the hardware boundary.
- [ ] Re-run focused tests and confirm they pass.

### Task 3: Restricted host helper and bootstrap contract

**Files:**
- Create: `scripts/cashpilot-nkn-agent.py`
- Modify: `scripts/bootstrap-worker.sh`
- Modify: `docker-compose.yml`
- Modify: `docker-compose.fleet.yml`
- Modify: `docker-compose.build.yml`
- Test: `tests/test_nkn_host_agent.py`
- Test: `tests/test_bootstrap_contract.py`
- Test: `tests/test_release_triggers.py`

**Interfaces:**
- Produces local API endpoints under `/v1/slots/ipv4-NNN` only.
- Enforces instance prefix `cashpilot-nkn-`, assignment CAS, hard CPU/RAM limits, official inner Docker image, direct-port proxies, and per-slot outbound routing.

- [ ] Write tests proving invalid names, assignments, resource bounds, and arbitrary commands are rejected.
- [ ] Run the helper/bootstrap tests and confirm they fail before implementation.
- [ ] Implement the stdlib helper, systemd unit, LXD prerequisites, socket permissions, and worker socket mount.
- [ ] Re-run helper/bootstrap/release-wiring tests and confirm they pass.

### Task 4: Verification, release, and test-sing adoption

**Files:**
- Modify: `docs/guides/nkn.md`
- Modify: `docs/ACTIVE_CONTEXT.md`

- [ ] Run targeted NKN tests, full pytest, and Ruff.
- [ ] Audit `git diff` and prove no protected-provider runtime or catalog file changed.
- [ ] Build/release the required UI and worker artifacts.
- [ ] Install/update only the NKN host helper and required worker socket mount on test-sing.
- [ ] Stop the LXD canary briefly, rename/adopt it without changing its data or Node ID, then resume it under assignment CAS.
- [ ] Verify heartbeat HTTP 200, LXD limits, inner Docker restart policy, public RPC, `PERSIST_FINISHED`, Fleet online count, and wallet lease continuity.
- [ ] Update NKN docs and `ACTIVE_CONTEXT.md` with fresh evidence, then rerun documentation tests.
