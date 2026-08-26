# EarnApp Official Runtime Canary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a separately scoped EarnApp Mac-emulation worker lane that can deploy one verified VN residential canary without changing protected provider runtimes.

**Architecture:** Keep the existing EarnApp account pool, logical-node recovery state machine, and `earnapp_wss` proxy qualification as the server authority. Add a catalog/runtime entry and a worker-side Mac identity runtime that consumes only a pinned, server-managed encrypted profile and the account-scoped proxy lease; link/verification remains explicit and read-only evidence is returned through heartbeat. The canary path is separate from generic auto-deploy and never reuses the worker-level proxy assignment.

**Tech Stack:** Python 3.14, FastAPI, Pydantic, SQLite/aiosqlite, Docker SDK, YAML catalog, pytest, shell/Node runtime assets.

## Global Constraints

- EarnApp supports `proxy` mode only and requires `alive` + `residential` + non-empty egress + latest `CID_SET/eligible` probe.
- The canary uses a distinct logical node ID, device ID, persistent `/etc/earnapp` volume, and provider-instance proxy lease.
- The canary proxy must be VN residential and have a different canonical egress from every active assignment.
- No provider container may be privileged, use Docker socket, use KVM, or request capabilities/devices outside the catalog allowlist.
- Account credentials and encrypted identity profiles are server-managed and are never emitted in heartbeat, logs, provider-instance specs, or public API responses.
- Failed deployment may release only the canary lease and remove only resources created by that canary attempt; it must not touch NKN LXD, MYST, or any protected provider.
- Do not import captured lab profiles, IDs, proxy credentials, or proprietary binaries into Git.
- No remote EarnApp unlink/delete is performed automatically.

---

### Task 1: Establish failing canary contracts

**Files:**
- Create: `tests/test_earnapp_canary_contract.py`
- Modify: `docs/superpowers/plans/2026-08-26-earnapp-official-runtime-canary.md`

**Interfaces:**
- Tests consume `app.provider_runtime`, `app.catalog`, `app.main`, `app.worker_api`, and `app.earnapp_canary`.
- Later tasks must provide `build_canary_spec`, `provision_canary`, and `worker_api._earnapp_provider_state` with the signatures asserted by the tests.

- [ ] **Step 1: Write the failing tests**

```python
def test_earnapp_is_proxy_only_and_catalog_is_active():
    runtime = provider_runtime.get("earnapp")
    assert runtime is not None
    assert runtime.modes == ("proxy",)
    service = catalog.get_service("earnapp")
    assert service["status"] == "active"
    assert service["egress"]["mode"] == "proxy"


def test_canary_spec_is_account_scoped_and_hardened():
    spec = earnapp_canary.build_canary_spec(
        logical_node_id="earnapp-canary-1",
        account_id=7,
        device_id="sdk-mac-test",
        proxy={"proxy_id": 12, "exit_ip": "203.0.113.10"},
        identity_asset_kind="mac_identity_profile",
    )
    assert spec["provider_slug"] == "earnapp"
    assert spec["labels"]["cashpilot.earnapp.logical_node_id"] == "earnapp-canary-1"
    assert spec["labels"]["cashpilot.earnapp.account_id"] == "7"
    assert spec["volumes"]["earnapp-canary-1-data"]["bind"] == "/etc/earnapp"
    assert spec["privileged"] is False
    assert "/var/run/docker.sock" not in str(spec)
    assert "/dev/kvm" not in str(spec)


def test_canary_spec_does_not_put_account_tokens_in_container_env_or_labels():
    spec = earnapp_canary.build_canary_spec(
        logical_node_id="earnapp-canary-1",
        account_id=7,
        device_id="sdk-mac-test",
        proxy={"proxy_id": 12, "exit_ip": "203.0.113.10", "username": "u", "password": "p"},
        identity_asset_kind="mac_identity_profile",
    )
    serialized = json.dumps(spec, sort_keys=True)
    assert "oauth-refresh-token" not in serialized
    assert "xsrf-token" not in serialized
    assert '"password": "p"' not in serialized


def test_worker_reports_earnapp_instance_state_without_secrets():
    state = worker_api._earnapp_provider_state(
        [
            {
                "name": "earnapp-canary-1",
                "status": "running",
                "labels": {
                    "cashpilot.provider": "earnapp",
                    "cashpilot.earnapp.logical_node_id": "earnapp-canary-1",
                    "cashpilot.earnapp.generation": "1",
                    "cashpilot.earnapp.device_id": "sdk-mac-test",
                },
            }
        ]
    )
    assert state["instances"][0]["logical_node_id"] == "earnapp-canary-1"
    assert "password" not in json.dumps(state)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `pytest -q tests/test_earnapp_canary_contract.py`

Expected: FAIL because the EarnApp catalog/runtime canary builder and worker state helper do not exist yet.

### Task 2: Register the official EarnApp proxy runtime

**Files:**
- Modify: `app/provider_runtime.py`
- Create: `services/bandwidth/earnapp.yml`
- Test: `tests/test_earnapp_canary_contract.py`

**Interfaces:**
- `provider_runtime.PROVIDERS["earnapp"]` exposes `("proxy",)` and collector kind `earnings`.
- Catalog declares the pinned public image, persistent critical volume, Mac profile runtime asset, proxy egress, and no privileged/device settings.

- [ ] **Step 1: Add the minimal provider-runtime entry and catalog contract**

Use the public image digest already verified in the repository research, declare `mac_identity_profile` as a server-managed encrypted asset, and keep account tokens out of Docker env. The catalog must set `requirements.residential_ip: true`, `requirements.vps_ip: false`, `devices_per_ip: 1`, and `deploy.automation: earnapp_mac_canary`.

- [ ] **Step 2: Run catalog and focused tests**

Run: `pytest -q tests/test_catalog.py tests/test_provider_modes.py tests/test_earnapp_canary_contract.py`

Expected: catalog/runtime assertions pass; canary-builder/state-helper tests remain RED until Tasks 3–4.

### Task 3: Add the account-scoped canary spec/provisioning lane

**Files:**
- Create: `app/earnapp_canary.py`
- Modify: `app/main.py`
- Modify: `app/database.py` only if a missing atomic helper is proven by a failing test
- Test: `tests/test_earnapp_canary_contract.py`

**Interfaces:**
- `build_canary_spec(logical_node_id: str, account_id: int, device_id: str, proxy: Mapping[str, Any], identity_asset_kind: str = "mac_identity_profile") -> dict[str, Any]` returns a worker `DeploySpec`-compatible mapping without credentials.
- `provision_canary(logical_node_id: str, worker_id: int, device_id: str) -> dict[str, Any]` assigns an active account, leases one scoped EarnApp proxy, binds the logical node, and returns only redacted node/lease metadata.
- `main` gets one owner-only canary endpoint that invokes the lane; generic `/api/deploy/{slug}` and auto-deploy remain unchanged.

- [ ] **Step 1: Add failing tests for atomic account/proxy provisioning**

```python
async def test_provision_canary_reuses_existing_node_and_never_worker_assignment(...):
    first = await earnapp_canary.provision_canary("earnapp-canary-1", worker_id, "sdk-mac-test")
    second = await earnapp_canary.provision_canary("earnapp-canary-1", worker_id, "sdk-mac-test")
    assert second["proxy_id"] == first["proxy_id"]
    assert await database.get_worker_proxy_assignment(worker_id) is None
```

- [ ] **Step 2: Run the test and confirm the exact missing behavior**

Run: `pytest -q tests/test_earnapp_canary_contract.py::test_provision_canary_reuses_existing_node_and_never_worker_assignment`

Expected: FAIL before the provisioning helper exists.

- [ ] **Step 3: Implement the smallest provisioning path**

Call the existing `assign_earnapp_account`, `lease_proxy_for_provider_instance("earnapp", worker_id, logical_node_id)`, and `bind_earnapp_node_runtime` helpers under their existing locks. Reject inactive accounts and missing eligible proxies; on bind/deploy preparation failure release only `earnapp/worker_id/logical_node_id`.

- [ ] **Step 4: Add the owner-only canary route**

The route accepts `worker_id`, `logical_node_id`, and `device_id`, calls provisioning, builds the redacted spec, and proxies it to the worker with the logical node slug. It must not accept account cookies or proxy credentials from the request body.

- [ ] **Step 5: Run focused server tests**

Run: `pytest -q tests/test_earnapp_canary_contract.py tests/test_earnapp_account_pool.py tests/test_earnapp_recovery.py`

Expected: all focused canary/account/recovery tests pass.

### Task 4: Add worker Mac-emulation runtime and heartbeat evidence

**Files:**
- Modify: `app/worker_api.py`
- Modify: `Dockerfile.worker`
- Create: `app/earnapp_runtime.py`
- Test: `tests/test_earnapp_canary_contract.py`
- Test: `tests/test_runtime_assets.py`

**Interfaces:**
- `worker_api._earnapp_provider_state(containers: list[Mapping[str, Any]]) -> dict[str, Any]` returns redacted instance evidence and logical-node generation fields.
- Worker deploy accepts `provider_slug="earnapp"` and materializes only the catalog-approved encrypted Mac profile asset into a read-only profile mount while keeping `/etc/earnapp` writable/persistent.
- Runtime uses a per-node `sdk-mac-*` identity, watchdog/restart policy, and sidecar egress; it does not use Docker socket, KVM, or privileged mode.

- [ ] **Step 1: Add failing tests for state evidence, runtime asset kind, and hardening**

```python
def test_worker_catalog_contains_earnapp_profile_asset_and_no_host_privilege():
    service = catalog.get_service("earnapp")
    assert service["deploy"]["runtime_assets"][0]["asset_kind"] == "mac_identity_profile"
    assert service["docker"].get("privileged", False) is False
    assert not service["docker"].get("devices")
```

- [ ] **Step 2: Run RED**

Run: `pytest -q tests/test_earnapp_canary_contract.py tests/test_runtime_assets.py`

Expected: FAIL on the missing asset kind/state helper.

- [ ] **Step 3: Implement runtime/state support**

Add the helper, include `app/earnapp_runtime.py` in `Dockerfile.worker`, extend the runtime asset allowlist with `mac_identity_profile`, and add EarnApp provider-state collection to `_send_heartbeat`. State contains only container status, logical node ID, generation, device ID, and observed egress/registration markers.

- [ ] **Step 4: Run focused worker/runtime tests**

Run: `pytest -q tests/test_earnapp_canary_contract.py tests/test_runtime_assets.py tests/test_worker_nkn_deploy.py`

Expected: all pass and NKN worker tests remain unchanged.

### Task 5: Verification boundary and live-canary preflight

**Files:**
- Modify: `docs/ACTIVE_CONTEXT.md` only after live evidence is collected
- Modify: `docs/research/repo-github-understanding.md` only if the implementation boundary needs recording

- [ ] **Step 1: Run local quality gates**

Run: `pytest -q tests/test_earnapp_canary_contract.py tests/test_earnapp_account_pool.py tests/test_earnapp_recovery.py tests/test_earnapp_collector.py tests/test_runtime_assets.py tests/test_catalog.py tests/test_provider_modes.py`; `ruff check app tests`; `python -m compileall -q app`; `git diff --check`.

- [ ] **Step 2: Audit protected-provider boundary**

Run: `git diff --name-only -- app/nkn* app/myst* services/bandwidth/nkn.yml services/bandwidth/mysterium.yml tests/test_nkn* tests/test_myst*`. Expected: no changed protected-provider files.

- [ ] **Step 3: Verify VPS preflight read-only**

Using `vps/vps-test-sing.txt` (not Azure CLI), verify worker release, NKN LXD/container/volume state, available VN residential proxy capacity, and whether the pinned EarnApp image/profile asset is present. Do not stop/recreate/remove NKN or MYST.

- [ ] **Step 4: Deploy exactly one canary**

Import/re-activate the authoritative account from Chrome profile 40 through the existing extension, select one latest `CID_SET/eligible` VN residential proxy, provision one logical node, deploy the canary, and verify container/volume labels, proxy egress, heartbeat, and authenticated `devices` evidence. On any failure, release only the canary lease and preserve the remote device/account.

- [ ] **Step 5: Record evidence and report remaining gaps**

Update `docs/ACTIVE_CONTEXT.md` only with verified IDs/statuses and explicitly leave EarnApp open until dashboard `activeDevices`/device link evidence is confirmed. Do not mark the provider complete from process/container status alone.
