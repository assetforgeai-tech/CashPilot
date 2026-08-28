# EarnApp Identity And LXD Canary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct newly generated EarnApp Mac/iOS identity profiles from the audited reference contract and add isolated iOS-Docker and Ubuntu-LXD canary lanes. MacOS/iOS remain Docker-only.

**Architecture:** The CashPilot server remains authoritative for logical nodes, encrypted identity profiles, account assignment, proxy leases, and workload verification. Existing Docker Mac nodes remain immutable. New canaries use separate logical nodes, volumes, identities, and residential leases; VN proxies select Mac/iOS and non-VN proxies select official Ubuntu in LXD. LXD transport is added only behind a capability-specific helper and is never used to recreate an existing node.

**Tech Stack:** Python 3.12+, FastAPI, SQLite/aiosqlite, Docker SDK, LXD REST/socket helper, Node runtime shims, pytest, Ruff, GitHub Actions.

**2026-08-28 execution checkpoint:** Tasks 1-3 are implemented locally and
focused verification passes. The owner confirmed that EarnApp account capacity
does not impose a node-count ceiling, so Task 4 is not blocked on importing a
second account. The owner explicitly removed MacOS/iOS LXD conversion from
scope; Ubuntu is the only EarnApp LXD lane.

## Global Constraints

- Do not recreate, migrate, rotate, unlink, or delete the existing Mac nodes, their volumes, identities, accounts, sidecars, or leases.
- Do not change NKN, MYST, or any provider marked `PROTECTED_DONE`.
- Use only residential proxies with the latest `earnapp_wss` eligible result; one proxy and one egress per EarnApp node.
- Generate and persist identity once per logical node; never rewrite an existing profile to add newly discovered fields.
- Do not add captured profiles, credentials, proprietary binaries, or raw live identifiers to Git.
- Treat online-without-workload as a failed/pending gate, not as proof that a transport change fixed usage.
- Do not implement anti-abuse bypasses; only satisfy the documented runtime wire contract and record external control-plane limits.

---

### Task 1: Freeze evidence and audit source artifacts

**Files:**
- Create: `docs/research/earnapp-identity-lxd-audit-2026-08.md`
- Modify: `docs/ACTIVE_CONTEXT.md` only after live evidence is collected
- Test: no source test changes

**Interfaces:**
- The audit records field sets, nested shapes, runtime entrypoint behavior, Docker/VM/LXD markers, and the known usage discrepancy without exposing secrets.

- [x] **Step 1: Record the current repository and live baseline.**

Run:

```powershell
git status --short --branch
git rev-parse HEAD
pytest -q tests/test_earnapp_identity.py tests/test_earnapp_lxd_runtime.py tests/test_earnapp_canary_contract.py
```

Store only counts, hashes, statuses, and redacted identifiers in the audit.

- [x] **Step 2: Compare reference profile shapes with generators.**

Use the authorized encrypted profile bundle under `D:\1. WORK_true\CashPilot\earnapp_new_update`, decrypt only in memory, and assert these reference sets:

```python
MAC_STATE = {
    "battery_percentage",
    "full_screen",
    "full_screen_ts",
    "idle_state",
    "monitor_power",
    "power_source",
    "session_state",
    "user_io",
}
IOS_FIELDS = {
    "codename",
    "conf_user",
    "confdir",
    "cp_id",
    "device_kind",
    "device_marketing",
    "device_model",
    "gw_ip",
    "iface_type",
    "is_swift",
    "mobile_type",
    "soc",
}
```

Do not write plaintext profiles to disk.

- [x] **Step 3: Document the usage finding.**

Record that node 1 has increasing `qualified_uptime`, earnings, and traffic, while node 2 is online and heartbeating but its usage plateaued; record that fresh WSS probes were eligible for all tested proxies. Leave transport migration as an unproven hypothesis.

- [ ] **Step 4: Commit the audit only after secret scan.**

Run `git diff --check` and a repository secret scan that excludes untracked diagnostic scripts; verify no token, password, profile plaintext, or full device ID was added.

### Task 2: Make new Mac/iOS identity generation match the audited contract

**Files:**
- Modify: `app/earnapp_identity.py`
- Modify: `app/earnapp_runtime.py`
- Test: `tests/test_earnapp_identity.py`

**Interfaces:**
- `generate_identity(node_id, "macos")` and `generate_identity(node_id, "ios")` return the audited top-level/nested shapes.
- `validate_identity(identity, platform)` rejects missing fields, invalid platform flags, and cross-platform mixtures.
- Existing persisted profiles continue to decrypt and validate; no migration rewrites them.

- [x] **Step 1: Add failing parity tests.**

Add tests that assert generated profiles contain the following exact keys and values:

```python
assert set(mac["new_state"]) == {
    "battery_percentage",
    "full_screen",
    "full_screen_ts",
    "idle_state",
    "monitor_power",
    "power_source",
    "session_state",
    "user_io",
}
assert set(ios) >= {
    "codename",
    "conf_user",
    "confdir",
    "cp_id",
    "device_kind",
    "device_marketing",
    "gw_ip",
    "iface_type",
    "is_swift",
    "mobile_type",
    "soc",
}
assert ios["new_state"]["session_state"] == "logged"
assert isinstance(ios["new_state"]["idle_state"], dict)
assert isinstance(json.loads(ios["usage"]["app_bytes"]), dict)
assert ios["ua"].startswith("earnapp/1 ")
```

- [x] **Step 2: Run the parity tests and confirm RED.**

Run `pytest -q tests/test_earnapp_identity.py -k parity`; the failure must identify the missing shape/value, not an import or fixture error.

- [x] **Step 3: Implement the smallest generator change.**

Extend only `_mac_identity`, `_ios_identity`, and their validators. Keep the
audited iOS `cp_id` constant `ios_com.brd.earnapp`; use independent CSPRNG
values for the per-node container/vendor IDs, local-unicast Wi-Fi/Mac
addresses, and serials. Keep the existing `sdk-mac-*`/`sdk-ios-*` derivation
and encrypted envelope unchanged.

- [x] **Step 4: Run green and regression tests.**

Run `pytest -q tests/test_earnapp_identity.py tests/test_earnapp_canary_contract.py`; then decrypt a sample in memory and verify persisted profile bytes are unchanged.

### Task 3: Add explicit platform-aware runtime contracts

**Files:**
- Modify: `app/earnapp_runtime.py`
- Modify: `app/earnapp_canary.py`
- Modify: `services/bandwidth/earnapp.yml`
- Test: `tests/test_earnapp_canary_contract.py`

**Interfaces:**
- `build_runtime_spec(..., platform="macos"|"ios")` emits the matching image, app ID, profile asset kind, and device prefix.
- A new `build_lxd_runtime_spec(..., platform="macos"|"ios")` is rejected until its helper capability and image manifest are verified; Ubuntu remains the only official LXD runtime in this phase.

- [x] **Step 1: Add tests that distinguish Docker and LXD contracts.**

Assert Mac/iOS Docker specs use no host socket, KVM, privilege, or undeclared device, and assert an unsupported LXD platform fails closed with a clear error.

- [x] **Step 2: Run focused tests and confirm the expected RED assertion.**

Run `pytest -q tests/test_earnapp_canary_contract.py -k platform`; confirm only the new contract is red.

- [x] **Step 3: Implement platform labels and asset-kind validation.**

Keep the current Mac contract intact for existing nodes, add the iOS parity fields, and make the catalog describe both Docker emulation lanes plus the separate Ubuntu LXD lane without changing protected provider entries.

- [x] **Step 4: Run catalog and protected-provider regression tests.**

Run `pytest -q tests/test_catalog.py tests/test_provider_modes.py tests/test_earnapp_canary_contract.py tests/test_nkn_lxd_runtime.py`.

### Task 4: Canary iOS and Ubuntu LXD sequentially

**Files:**
- Modify: `app/earnapp_deploy.py` only if a failing test proves a missing platform route
- Modify: `app/worker_api.py` only if a failing test proves a missing worker endpoint
- Test: `tests/test_earnapp_auto_deploy.py`, `tests/test_earnapp_lxd_runtime.py`
- Documentation after evidence: `docs/ACTIVE_CONTEXT.md`

**Interfaces:**
- Each canary has a fresh logical node, persistent volume/guest, unique identity, account binding, and exclusive proxy lease.
- iOS uses a VN residential proxy; Ubuntu uses a non-VN residential proxy and LXD limits from authoritative Settings.
- Deployment is sequential and a failed canary cannot block another provider or release an unrelated lease.

- [x] **Step 1: Run read-only preflight on the target worker.**

Verify worker version/heartbeat, public IPv4 slots, available eligible VN/non-VN residential proxies, active account assignment, LXD helper health, and absence of target logical-node IDs.

- [ ] **Step 2: Deploy the iOS canary.**

Use a new logical node and new volume/sidecar. Verify boot identity fields, `sdk-ios-*`, proxy egress, heartbeat, dashboard `activeDevices`, and a positive usage/workload delta. Do not touch either existing Mac node.

- [ ] **Step 3: Deploy the Ubuntu LXD canary.**

Use a different logical node and non-VN residential proxy. Verify guest `1 CPU/1024 MiB` defaults (or explicitly configured Settings), `boot.autostart`, inner `restart: always`, official runtime, unique `sdk-node-*`, heartbeat, device presence, and workload delta.

- [ ] **Step 4: Exercise restart persistence.**

Restart only each new canary, then verify unchanged device ID, account, platform, volume/guest, proxy lease, and authenticated workload evidence.

- [ ] **Step 5: Remove only failed disposable canary resources.**

If a canary fails, use its generation/device CAS tuple to remove only that logical node and release only its lease; never remove an existing node or remote EarnApp device.

### Task 6: Quality gates and closeout

**Files:**
- Modify: `docs/ACTIVE_CONTEXT.md`
- Modify: `docs/guides/earnapp.md`
- Modify: `docs/research/repo-github-understanding.md`

- [ ] **Step 1: Run all local gates.**

Run `pytest -q`, `ruff check .`, `python -m compileall -q app`, `git diff --check`, and a final secret scan.

- [ ] **Step 2: Review blast radius.**

Compare protected provider YAML hashes and inspect the diff for NKN/MYST/provider-runtime changes. Any unexpected change blocks release.

- [ ] **Step 3: Release only after evidence.**

Create a scoped commit/PR and release only the changed UI/worker artifacts after CI passes. Redeploy only the component required by the changed path; do not bulk redeploy the fleet.

- [ ] **Step 4: Update status honestly.**

Mark iOS or Ubuntu as complete only with authenticated device presence, online state, restart persistence, and workload delta. Keep EarnApp open (not `PROTECTED_DONE`) if any platform lacks those gates.
