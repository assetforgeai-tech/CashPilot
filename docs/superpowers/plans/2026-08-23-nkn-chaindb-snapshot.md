# NKN ChainDB Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional, integrity-verified NKN ChainDB snapshot publisher and consumer flow that accelerates new NKN node bootstrap without changing existing wallet, identity, lease, LXD, or protected-provider contracts.

**Architecture:** A pure NKN snapshot contract module validates immutable manifests, archive names, checksums, sizes, age, and safe tar paths. A dedicated publisher service on the separate ChainDB VPS performs a clean stop/archive/start cycle and uploads immutable objects to a private R2 prefix, publishing `latest.json` last. New NKN deploys receive a short-lived R2 download URL and restore only `ChainDB/` into a staging directory before atomically swapping it into a newly-created node; invalid or unavailable snapshots fall back to ordinary ChainDB sync. The CashPilot UI stores publisher/R2 settings encrypted, exposes a masked NKN Runtime panel, and provides an owner-only deployment action over SSH without exposing credentials.

**Tech Stack:** Python 3.12+ stdlib (`tarfile`, `hashlib`, `subprocess`, AWS SigV4), FastAPI/Pydantic, SQLite encrypted config, Bash/systemd, Docker/LXD, Cloudflare R2 S3 API, pytest, Ruff.

## Global Constraints

- Modify only NKN snapshot/runtime, dashboard Settings/API, worker/LXD restore, publisher deployment wiring, tests, and NKN documentation.
- Do not modify provider catalog/runtime/collector code for protected providers.
- Preserve the active NKN node's identity, wallet, wallet lease, assignment version, LXD instance, inner Docker container, and volume.
- Snapshot archives contain `ChainDB/` only; never replace `config.json`, `wallet.json`, `wallet.pswd`, `ChainDB.config`, or identity metadata.
- Never stream bytes into a live `ChainDB`; restore through staging, checksum verification, safe extraction, backup rename, and atomic rename.
- R2 remains private. Use an isolated bucket when the credential allows it; otherwise use an isolated prefix and report the limitation before upload.
- The snapshot path is optional acceleration. Missing, stale, invalid, or failed snapshots must not deadlock provider auto-deploy; the node falls back to normal sync.
- Do not print, log, return, commit, or put in manifests any R2 secret, SSH password/key, wallet JSON/password, or presigned URL beyond its intended request lifetime.
- No Azure CLI. No bulk redeploy, wallet rotation, lease rotation, cleanup, or live mutation outside the explicitly isolated publisher/canary sequence.
- Preserve pre-existing untracked `site/` and unrelated worktree changes.

---

### Task 1: Snapshot contract and implementation plan validation

**Files:**
- Create: `app/nkn_chaindb.py`
- Test: `tests/test_nkn_chaindb.py`
- Modify: `docs/superpowers/plans/2026-08-23-nkn-chaindb-snapshot.md`

**Interfaces:**
- `snapshot_object_key(prefix, height, created_at, sha256) -> str`
- `build_manifest(...) -> dict[str, Any]`
- `validate_manifest(manifest, *, now=None, max_age_seconds=...) -> dict[str, Any]`
- `validate_archive_members(names) -> None`
- `verify_file(path, expected_sha256, expected_size) -> dict[str, Any]`
- `retained_snapshot_keys(keys, keep=...) -> list[str]`

- [ ] Write failing tests for immutable key shape, required manifest fields, digest/size/height validation, age rejection, path traversal rejection, and retention ordering.
- [ ] Run `pytest tests/test_nkn_chaindb.py -q` and observe the expected import/function failures.
- [ ] Implement only the pure validation and hashing contract; keep network/process operations out of this module.
- [ ] Re-run the focused tests and then `ruff check app/nkn_chaindb.py tests/test_nkn_chaindb.py`.

### Task 2: R2 signing and publisher/consumer command contracts

**Files:**
- Create: `scripts/nkn_chaindb_r2.py`
- Create: `scripts/nkn_chaindb_publisher.py`
- Create: `scripts/nkn_chaindb_restore.py`
- Test: `tests/test_nkn_chaindb_r2.py`
- Test: `tests/test_nkn_chaindb_scripts.py`

**Interfaces:**
- `presign_get(endpoint, bucket, key, access_key, secret_key, expires) -> str`
- `presign_put(...) -> str`
- publisher `--config`, `--once`, and `--verify-only` modes
- restore `--manifest-url`, `--archive-url`, `--data-dir`, `--dry-run`

- [ ] Write failing tests proving AWS SigV4 URLs do not expose secret keys, object keys are encoded safely, publisher command order is stop/archive/start/upload/publish, and restore rejects unsafe tar members and checksum/size mismatches.
- [ ] Run the focused tests and observe failures caused by missing scripts/functions.
- [ ] Implement standard-library SigV4 helpers and subprocess contracts with no shell interpolation of user-controlled paths.
- [ ] Implement publisher cold snapshot flow: verify node, stop inner container cleanly, stream `tar` through `zstd`, calculate digest/size, restart node before upload, upload immutable object, verify remote HEAD, publish `latest.json` last, and prune only old local archives after success.
- [ ] Implement restore flow: fetch/validate manifest, download immutable archive to staging, verify digest/size, inspect safe members, extract `ChainDB.new`, stop target, rename current DB to timestamped backup, atomically install new DB, restart and return rollback instructions/results.
- [ ] Re-run focused tests and verify no secret appears in stdout/stderr fixtures.

### Task 3: Worker NKN restore integration with fallback

**Files:**
- Modify: `app/nkn_lxd_runtime.py`
- Modify: `app/nkn_runtime.py`
- Modify: `app/worker_api.py`
- Modify: `scripts/cashpilot-nkn-agent.py`
- Modify: `Dockerfile.worker`
- Test: `tests/test_nkn_lxd_runtime.py`
- Test: `tests/test_worker_nkn_deploy.py`
- Test: `tests/test_worker_nkn_sync.py`

**Interfaces:**
- NKN deploy assignment accepts optional `chaindb_snapshot` metadata containing only manifest and short-lived archive URL.
- Worker/helper returns redacted `snapshot_status` values (`restored`, `skipped`, `fallback`, `failed`).

- [ ] Write failing tests proving snapshot metadata is passed only to NKN, wallet/config/identity fields are preserved, restore is attempted only for a newly-created slot, and restore failure starts normal sync rather than failing the worker heartbeat or another provider.
- [ ] Run focused tests and observe failures.
- [ ] Implement the minimal LXD-helper restore hook using the standalone restore script inside the NKN instance; do not widen the helper to arbitrary commands.
- [ ] Keep adoption/existing-container paths snapshot-free and preserve current node 1 data.
- [ ] Re-run focused tests, including lease-guard and secret-redaction regressions.

### Task 4: Server snapshot settings, presigned URL issuance, and publisher deploy action

**Files:**
- Modify: `app/main.py`
- Modify: `app/templates/settings.html`
- Modify: `app/static/js/app.js`
- Modify: `app/database.py` only if a secret-key suffix is missing
- Test: `tests/test_nkn_chaindb_settings.py`
- Test: `tests/test_nkn_auto_deploy.py`
- Test: `tests/test_settings_contract.py`

**Interfaces:**
- `_nkn_chaindb_settings(config) -> dict[str, Any]` validates bucket, endpoint, prefix, retention, max age, and publisher connection fields.
- `GET /api/nkn/chaindb/status` returns masked configuration and latest manifest metadata only.
- `POST /api/nkn/chaindb/publisher/deploy` is owner-only, validates the complete payload, and returns redacted deployment evidence.
- NKN slot deploy obtains a presigned GET URL only when snapshot settings are enabled and the manifest validates.

- [ ] Write failing tests for safe defaults/bounds, masked R2/SSH values, owner-only deployment, no secret in response/log payload, and snapshot metadata propagation to NKN only.
- [ ] Run focused tests and observe failures.
- [ ] Implement settings normalization and UI fields for private R2 endpoint/bucket/prefix, retention/max age, publisher host/port/user, SSH key/password, enable toggle, and deploy button; never render secret values.
- [ ] Implement a bounded SSH deployment command using an argv list and temporary secret material with strict permissions; redact all command output and delete temporary files in `finally`.
- [ ] Implement server-side manifest validation and presigned URL generation; on R2/network errors return `snapshot_status=unavailable` and let ordinary NKN sync proceed.
- [ ] Re-run focused tests and browser-free JavaScript parsing.

### Task 5: Bootstrap, image, systemd publisher artifacts, and documentation

**Files:**
- Create: `scripts/cashpilot-nkn-chaindb-publisher.service`
- Create: `scripts/cashpilot-nkn-chaindb-publisher.timer`
- Modify: `scripts/bootstrap-worker.sh` only for optional consumer prerequisites (no publisher credentials)
- Modify: `Dockerfile.worker`
- Modify: `docs/guides/nkn.md`
- Modify: `docs/ACTIVE_CONTEXT.md`
- Test: `tests/test_bootstrap_contract.py`
- Test: `tests/test_nkn_chaindb_docs.py`

- [ ] Write failing contract tests for publisher service hardening, daily timer, private config permissions, no credentials in bootstrap, and documentation claims.
- [ ] Run focused tests and observe failures.
- [ ] Add publisher installation artifacts that run as a dedicated non-root service where possible, use `flock`, bounded disk checks, `Restart=on-failure`, and `OnFailure` logging without secrets.
- [ ] Ensure consumer image contains only the restore helper dependencies needed for NKN; do not add R2 credentials or general SSH tooling to the worker.
- [ ] Document snapshot fallback, rollback, retention, private R2 requirements, and protected-node rules.
- [ ] Re-run focused tests and documentation checks.

### Task 6: Verification, release, and isolated live canary

**Files:**
- No additional source files unless a verified test exposes a defect.
- Update: `docs/ACTIVE_CONTEXT.md` with evidence only after live checks.

- [ ] Run targeted NKN/snapshot tests, full `pytest`, `ruff check`, `ruff format --check`, `python -m compileall`, and `git diff --check`.
- [ ] Compare changed paths against the protected-provider matrix and confirm no provider catalog/runtime/collector file changed.
- [ ] Verify both UI and worker release artifacts before any redeploy; do not redeploy the active test-sing worker unless the worker image actually changed.
- [ ] Preflight the dedicated snapshot VPS disk, Docker/NKN data path, systemd, and R2 permissions; resize disk before any 5.8 GB archive operation if headroom is insufficient.
- [ ] Deploy publisher only to `vps-nkn-chaindb`, create the first immutable snapshot after a clean stop/start, and verify remote digest/size/manifest without exposing credentials.
- [ ] Restore only into an isolated disposable NKN canary slot/VPS; verify node identity, wallet assignment, `PERSIST_FINISHED`, heartbeat/Fleet status, and rollback path. Never replace the successful test-sing node's ChainDB during the first restore.
- [ ] If all evidence passes, document exact object key/digest/height/timestamps (not secrets), snapshot status, and remaining operational gaps; otherwise report the blocker and leave live state unchanged.
