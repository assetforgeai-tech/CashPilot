# EarnApp Ubuntu Docker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move the EarnApp Ubuntu lane from LXD to a dedicated Docker runtime while preserving the existing account, proxy, UUID, and restart contracts.

**Architecture:** Ubuntu uses the same dedicated Docker deployment lane as MacOS/iOS, but with an official Linux runtime image and an Ubuntu identity profile. The existing LXD route remains available for legacy state and is not mutated by this change. The Docker entrypoint removes Docker markers, persists a per-node machine-id/hostname, installs the official EarnApp runtime once into the node volume, and retries registration through the assigned proxy.

**Tech Stack:** Python/FastAPI, Pydantic, Docker SDK, pytest, Bash entrypoint, Ubuntu 24.04.

## Global Constraints

- Only EarnApp Ubuntu is changed; MacOS/iOS and protected providers remain untouched.
- Existing Ubuntu logical node UUID, account, proxy lease, generation, and volume state are preserved when possible.
- No generic/raw Docker deployment is opened; Ubuntu uses the dedicated EarnApp route and strict image/runtime labels.
- No credentials or proxy secrets are written to Git or emitted in logs.

### Task 1: Contract and policy

**Files:** `app/provider_runtime.py`, `app/earnapp_runtime.py`, `app/worker_api.py`, `tests/test_earnapp_multiplatform_contract.py`, `tests/test_earnapp_ubuntu_policy.py`, `tests/test_earnapp_canary_contract.py`

- Add `ubuntu` Docker as the explicit backend for new deployments.
- Keep LXD validation/lifecycle for legacy nodes whose persisted backend is LXD.
- Add a strict Ubuntu Docker image contract and identity/profile validation.

### Task 2: Ubuntu Docker image/runtime

**Files:** `app/earnapp_canary.py`, `scripts/build_earnapp_canary_image.py`, `app/earnapp_runtime.py`, `tests/test_earnapp_canary_contract.py`

- Build a pinned Ubuntu image from the official installer path.
- Add the marker removal, persistent machine-id, hostname, OS/architecture logging, proxy readiness, installer checksum, and registration retry stages.
- Generate a unique Ubuntu identity per logical node and preserve it in the encrypted asset/volume.

### Task 3: Route/lifecycle wiring

**Files:** `app/main.py`, `app/worker_api.py`, `app/earnapp_canary.py`, `tests/test_earnapp_auto_deploy.py`, `tests/test_earnapp_lxd_runtime.py`

- Route Ubuntu canary deploy/redeploy to the Docker lane.
- Allow lifecycle/proxy rotation to dispatch by persisted backend.
- Keep legacy LXD nodes readable and removable without converting them implicitly.

### Task 4: Verification and canary

- Run focused tests, then full EarnApp/provider tests.
- Build/preload the Ubuntu image on `test-sing` only.
- Recreate only `earnapp-mp-ubuntu-20260831-c`, verify exact UUID, proxy egress, `linked:true`, country, usage delta, and restart persistence.
- Update `docs/ACTIVE_CONTEXT.md` and research documentation with evidence and residual risks.
