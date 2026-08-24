# NKN Shared Snapshot Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Download each immutable NKN ChainDB snapshot digest once per worker VPS and reuse it read-only across sequential LXD node restores.

**Architecture:** The restricted host helper owns a persistent host cache keyed by the manifest SHA-256. It serializes cache population with a file lock, downloads into a `.partial` file, validates size and SHA-256, and atomically renames the completed archive. Each NKN LXD instance receives the cache directory as a read-only disk device and the existing restore tool consumes the local archive while leaving `restore_archive()` unchanged.

**Tech Stack:** Python 3.10+ standard library, `fcntl.flock` on Ubuntu, LXD disk devices, pytest, Bash/systemd.

## Global Constraints

- Do not modify the publisher, R2 object layout, `latest.json`, or publisher timer.
- Do not modify `restore_archive()` or its staging/stop/swap/start/verify/rollback sequence.
- Do not alter wallet leases, wallet/config files, node identities, public-IP routing, LXD resource limits, or protected providers.
- A missing, stale, corrupt, unavailable, or unmountable snapshot must fall back to normal NKN sync and must not block another node or provider.
- Presigned URLs must not be written into LXD files, persistent worker state, logs, cache metadata, or documentation.
- Cache archives are immutable and keyed only by lowercase SHA-256; live `ChainDB` directories are never shared.
- Do not commit, push, release, or deploy until verification passes and the active user authorization covers that action.

---

### Task 1: Host Cache Contract

**Files:**
- Create: `scripts/nkn_chaindb_cache.py`
- Create: `tests/test_nkn_chaindb_cache.py`

**Interfaces:**
- Produces: `ensure_cached_archive(url, *, expected_sha256, expected_size, cache_root, keep=2) -> CacheResult`
- Produces: `invalidate_cached_archive(path, *, cache_root) -> None`
- `CacheResult` exposes `path`, `sha256`, `size_bytes`, and `cache_hit` without retaining the URL.

- [x] Write failing tests proving one URL fetch for repeated calls with the same digest, `.partial` cleanup, size and digest rejection, corrupt-cache replacement, lock serialization, atomic rename, bounded retention, and secret-free errors/results.
- [x] Run `pytest tests/test_nkn_chaindb_cache.py -q` and confirm failure because the module does not exist.
- [x] Implement the minimal persistent cache with a Linux `flock` and a process-local fallback used only by non-Linux test environments.
- [x] Re-run the focused tests and `ruff check scripts/nkn_chaindb_cache.py tests/test_nkn_chaindb_cache.py`.

### Task 2: Host-to-LXD Read-Only Handoff

**Files:**
- Modify: `scripts/cashpilot-nkn-agent.py`
- Modify: `scripts/nkn_chaindb_restore.py`
- Modify: `tests/test_nkn_host_agent.py`
- Modify: `tests/test_nkn_chaindb_scripts.py`

**Interfaces:**
- Host helper creates or reuses the verified cache archive before restore.
- Host helper adds only the named `nkn-chaindb-cache` LXD disk device with `readonly=true`.
- Restore request accepts `archive_path=/var/lib/cashpilot/nkn-chaindb-cache/<sha256>.tar.zst` and does not call the URL downloader for that path.

- [x] Write failing tests proving the presigned URL stays on the host, the cache device is read-only, multiple slots resolve the same digest path, local-cache restore does not unlink the shared archive, and cache/mount/restore failure returns `fallback` while starting normal sync.
- [x] Run the focused tests and confirm the expected failures.
- [x] Implement the host cache call, restricted LXD device setup, and local archive request branch without editing `restore_archive()`.
- [x] Re-run the host-agent and restore tests, including rollback and secret-redaction regressions.

### Task 3: Bootstrap, Artifacts, Documentation, and Verification

**Files:**
- Modify: `scripts/bootstrap-worker.sh`
- Modify: `tests/test_bootstrap_contract.py`
- Modify: `tests/test_nkn_chaindb_artifacts.py`
- Modify: `docs/guides/nkn.md`
- Modify: `docs/ACTIVE_CONTEXT.md` only after fresh verification.

**Interfaces:**
- Bootstrap installs the cache module and creates `/var/lib/cashpilot/nkn-chaindb-cache` without credentials.
- The NKN host helper remains the only component with LXD and cache-write authority.

- [x] Write failing artifact/bootstrap tests for cache installation, persistent directory permissions, no credentials, and no publisher changes.
- [x] Implement only the NKN cache installation/runtime prerequisites.
- [ ] Run targeted NKN tests, full pytest, Ruff, compileall, `git diff --check`, and a changed-path audit against protected providers.
- [x] If live validation is authorized, update only the NKN helper/consumer on a disposable canary VPS, prove one download for two restore attempts or a cache hit, and preserve all existing successful nodes.
- [x] Record only verified evidence and remaining gaps; leave commit/push/release/deploy for an explicitly authorized closeout step.
