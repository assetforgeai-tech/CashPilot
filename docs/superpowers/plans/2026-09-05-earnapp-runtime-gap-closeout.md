# EarnApp Runtime Gap Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close verified runtime, fake-proxy, identity, retry and persistence gaps for generic Docker MacOS/iOS/Ubuntu EarnApp images before isolated canary deployment.

**Architecture:** Keep platform identity profiles encrypted and per logical node. Build generic images from external, content-addressed runtime bundles; bind only proxy configuration and a writable per-node state volume at deploy time. Use redsocks plus fail-closed iptables for TCP, explicitly report DNS/UDP limitations, and preserve source runtime retry/cooldown behavior without importing host-bound fingerprint values.

**Tech Stack:** Python, Dockerfile generation, pytest, Ruff, redsocks, iptables, GHCR immutable digests.

## Global Constraints

- Do not copy `BOUND_FP_HASH`, `BOUND_FP_DISKS`, encrypted source profiles, cookies, tokens or proxy credentials into Git or generic images.
- Preserve exact device UUID and identity on restart; a proxy change is a separate recreate/route operation under existing lease authority.
- Do not change PROTECTED_DONE providers or mutate live VPS nodes during this phase.
- Do not claim absolute kernel, UDP, DNS or WebRTC concealment; verify and document the actual route.
- A runtime is canary-ready only after tests, manifest validation, image labels, proxy egress evidence and restart persistence checks pass.

### Task 1: Fix external bundle resolution

**Files:**
- Modify: `scripts/build_earnapp_canary_image.py`
- Test: `tests/test_earnapp_canary_contract.py`

- [ ] Add a failing test asserting `default_source_dir("macos")`, `default_source_dir("ios")` and `default_source_dir("ubuntu")` resolve from the repository root, not the worktree parent.
- [ ] Run the focused test and observe the expected path failure.
- [ ] Implement root discovery using `ROOT` as the repository root and `ROOT.parent.parent / "earnapp_new_update"` only when that external bundle exists; otherwise fail with a descriptive message.
- [ ] Re-run the focused test and verify it passes.

### Task 2: Pin the latest verified runtime bundles

**Files:**
- Modify: `app/earnapp_runtime.py`
- Test: `tests/test_earnapp_canary_contract.py`
- Docs: `docs/research/earnapp-20260905-three-platform-baseline.md`

- [ ] Add failing assertions for MacOS `1.660.577`, iOS source bundle hashes, Ubuntu private digest, and rejection of bound-only artifacts.
- [ ] Run those tests and verify they fail only for missing contract data.
- [ ] Implement immutable manifest metadata and source-bound artifact rejection without embedding profiles or credentials.
- [ ] Re-run focused tests and verify all pass.

### Task 3: Make proxy route behavior explicit and testable

**Files:**
- Modify: `app/earnapp_runtime.py`
- Test: `tests/test_earnapp_canary_contract.py`, `tests/test_earnapp_proxy_probe.py`
- Docs: `docs/earnapp-private-runtime.md`

- [ ] Add failing tests requiring separate declarations for TCP proxying, IPv6 drop, DNS policy and UDP capability; require no generic/raw host network mode.
- [ ] Run focused tests and verify failure.
- [ ] Implement only the smallest contract change: preserve redsocks TCP redirect, drop IPv6, make DNS mode explicit (`direct_udp53` or `proxy_dns`), and expose route evidence fields without claiming zero leak.
- [ ] Re-run focused proxy tests and shell syntax checks.

### Task 4: Preserve source retry/cooldown/watchdog behavior

**Files:**
- Modify: `app/earnapp_runtime.py`, `scripts/build_earnapp_canary_image.py`
- Test: `tests/test_earnapp_canary_contract.py`, `tests/test_earnapp_lifecycle.py`

- [ ] Add failing tests for bounded registration retry, tunnel-decline cooldown clamp, proxy-dead classification and restart persistence of UUID.
- [ ] Run tests to verify red state.
- [ ] Implement generated runtime wrappers from the verified external bundle; do not replace newer Mac/iOS entrypoints with older VPS copies.
- [ ] Verify each generated wrapper with `bash -n`, `node --check` where applicable, artifact hashes and focused tests.

### Task 5: Build manifests and generic images locally

**Files:**
- Modify: `scripts/build_earnapp_canary_image.py`
- Test: `tests/test_earnapp_canary_contract.py`
- Create: `docs/research/earnapp-runtime-gap-audit-20260905.md`

- [ ] Stage clean external contexts for all three platforms.
- [ ] Verify manifests contain only non-secret runtime artifacts and labels match platform/appid/device prefix.
- [ ] Build local images without source host fingerprint values; inspect Entrypoint, Env, labels, capabilities and volume contract.
- [ ] Record image IDs and hashes in the audit document.

### Task 6: Full verification and canary gate

**Files:**
- No live source edits.
- Evidence: `docs/research/earnapp-runtime-gap-audit-20260905.md`

- [ ] Run focused EarnApp tests, full pytest, Ruff and diff checks.
- [ ] Treat unrelated compose-release catalog failures separately; do not weaken those tests.
- [ ] Prepare an impact map for `vps-test-us`; only after explicit deployment authorization, canary one isolated node per OS with distinct eligible proxies.
- [ ] Verify online, positive usage, exact UUID persistence and restart behavior before expanding node count.
