# EarnApp Production Policy and Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hoàn thiện EarnApp production cho macOS/iOS/Ubuntu Docker với policy lifecycle không chồng chéo, account-token recovery/auto-login có kiểm soát, proxy rotation an toàn, runtime clone từ VPS nâng cấp, private GHCR và canary xác nhận usage.

**Architecture:** Collector là nguồn dữ liệu EarnApp mỗi 60 phút; lifecycle scheduler 5 phút chỉ quyết định recovery từ snapshot mới nhất. Offline chỉ restart tại chỗ; banned hoặc proxy rotation tạo node mới sau khi xóa device remote; auth failure xử lý account/token, không nhầm với node offline. Chrome extension giữ một profile cho một account, tự động login chỉ khi operator bật và account đang ở trạng thái cần refresh.

**Tech Stack:** Python/FastAPI, SQLite/aiosqlite, APScheduler, httpx, Docker, Chrome Manifest V3 extension, GHCR, pytest.

## Global Constraints

- Giữ nguyên scheduler restart 5 phút hiện tại cho node `offline` iOS/Ubuntu; không xóa behavior do operator đã chủ động cấu hình.
- Không dùng LXD cho EarnApp; cả macOS, iOS, Ubuntu chạy Docker lane hiện hành.
- Proxy fail-closed; không fallback trực tiếp; mỗi node một proxy/egress độc lập.
- Account suspended/locked: không quarantine; release proxy ngay sau khi local runtime bị dừng/xóa và lease CAS xác nhận. Remote device cleanup tiếp tục idempotent độc lập, không giữ proxy chỉ vì remote API chậm.
- Không chuyển UUID/device đang link trực tiếp giữa account; failover account phải tạo node mới.
- Không release proxy cũ trước khi remote device deletion thành công hoặc có xác nhận device không tồn tại.
- Không đụng provider khác hoặc protected baseline.
- Không lộ cookie, OAuth token, XSRF token, SSH key, GHCR token trong log, test output, image hoặc PR.
- Runtime/binary/image sau khi chốt phải pin digest/SHA-256; UUID, volume, credentials không clone từ reference VPS.
- Clone fidelity bắt buộc bao gồm binary, image filesystem, entrypoint, supervisor/watchdog, LAN identity/IP mapping, interface metadata, redsocks/iptables route, DNS behavior, proxy type/auth, registration, link retry, cooldown và follow; từng mục phải có hash/diff/evidence.
- Không sao chép cấu hình làm yếu TLS như `NODE_TLS_REJECT_UNAUTHORIZED=0` sang production nếu canary không chứng minh bắt buộc; nếu bắt buộc phải ghi nhận risk và giới hạn riêng cho EarnApp container.
- Token sync không chạy định kỳ vô điều kiện; chỉ chạy khi cookie thay đổi, operator bấm sync, hoặc server đánh dấu account cần refresh.

## Current `Node recovery` Meaning

`Node recovery` hiện là lớp bảo vệ local runtime/lease khi node EarnApp mất heartbeat hoặc worker không còn container:

- `RECOVERY_HOLD` giữ logical node và proxy lease trong một khoảng thời gian để tránh reclaim nhầm khi worker vừa reboot hoặc heartbeat trễ.
- Replacement ticket giới hạn một lần thay thế, chống hai tiến trình cùng recreate một node.
- `Recreate preserves identity and does not link` nghĩa là API recreate hiện giữ device identity/volume/logical binding cũ, chỉ dựng lại runtime; nó **không** gọi EarnApp `link_device`.
- Cơ chế này phù hợp cho recovery local/offline, nhưng không đủ cho policy mới của `banned` và proxy rotation. Hai trường hợp đó phải remote-delete device rồi tạo identity/UUID/volume mới và link lại.

## Task 1: Freeze and Test the Unified Policy

**Files:**
- Modify: `app/earnapp_lifecycle.py`
- Modify: `app/main.py`
- Test: `tests/test_earnapp_lifecycle.py`
- Create: `tests/test_earnapp_policy_matrix.py`

**Policy matrix:**

```text
offline       -> restart, preserve identity/volume/proxy; retain 5-minute retry
banned        -> remote delete; fresh node; same account/settings; relink
proxy_bad     -> remote delete; release old lease; fresh node; new proxy; relink
AUTH_FAILED   -> mark account AUTH_FAILED; alert; retry token refresh; no node restart
suspended     -> mark account ACCOUNT_LOCKED; cleanup; release proxy immediately
healthy       -> no mutation
```

- [x] Write failing tests asserting each row and asserting banned never maps to restart.
- [ ] Test earnings boundary: one recovery decision after `earnings_update_in_ms` resets; no duplicate action during the same cycle.
- [x] Run `pytest tests/test_earnapp_lifecycle.py tests/test_earnapp_policy_matrix.py -q` and confirm expected failures.
- [x] Implement the smallest pure decision change; keep 5-minute offline scheduling.
- [x] Run the focused tests; `38 passed` on 2026-09-08.

## Task 2: Durable Account Auth State and Failover

**Files:**
- Modify: `app/database.py`
- Modify: `app/earnapp_accounts.py`
- Modify: `app/collectors/earnapp.py`
- Modify: `app/main.py`
- Modify: `app/routers/earnapp_accounts.py`
- Test: `tests/test_earnapp_account_pool.py`, `tests/test_earnapp_collector.py`

- [x] Add durable auth evidence fields: `last_auth_success_at`, `last_auth_failure_at`, `auth_failure_kind`, `needs_token_refresh`.
- [ ] Classify auth rejection, account suspended/locked, proxy blocked, and route failure separately.
- [x] On auth failure, mark account and expose dashboard-visible auth evidence; do not restart every node.
- [ ] Implement failover as a transaction: remote-delete old device, retire old logical node, assign least-loaded `ACTIVE` account, lease eligible proxy, create fresh node.
- [ ] If no active account exists, keep node pending and retry silently; do not release a healthy proxy solely because token is expired.
- [ ] If account is suspended/locked, stop/remove local runtime, release its proxy immediately after lease CAS confirmation, and retry remote device cleanup independently without quarantining the proxy.
- [ ] Add race tests for two nodes failing against one account and for concurrent failover.

## Task 3: Remote Device Deletion and Fresh Replacement Transaction

**Files:**
- Modify: `app/collectors/earnapp.py`
- Modify: `app/main.py`
- Modify: `app/database.py`
- Modify: worker API/runtime files located by `rg -n "docker-nodes.*DELETE|link_device|device_statuses" app worker services`
- Test: `tests/test_earnapp_recovery.py`, `tests/test_earnapp_canary_contract.py`

- [x] Add authenticated remote-device delete with idempotent “already absent” success.
- [ ] Add confirmation evidence to the replacement transaction before releasing a lease.
- [x] Banned path now performs remote delete -> remove runtime -> release local binding -> clear identity; next sequential deploy creates fresh identity. Proxy rotation uses the same remote-delete gate.
- [ ] Keep existing recreate endpoint for local recovery only; document that it preserves identity and does not link.
- [ ] Fail closed to `RECOVERY_HOLD` when remote deletion or worker acknowledgement is uncertain.
- [ ] Test idempotency, remote-delete failure, duplicate replacement ticket, and reboot recovery.

## Task 4: Earnings Collector and Scheduler De-duplication

**Files:**
- Modify: `app/main.py`
- Modify: `app/collectors/earnapp.py`
- Modify: `app/earnapp_lifecycle.py`
- Test: `tests/test_earnapp_collector.py`, `tests/test_earnapp_lifecycle.py`

- [ ] Keep collector interval at 60 minutes.
- [ ] Keep lifecycle interval at 5 minutes for observation and offline restart.
- [ ] Persist `earnings_cycle_id`, `earnings_zero_observed_at`, and `last_recovery_cycle_id`.
- [ ] Use account `earnings_update_in_ms` as the cycle boundary; reset counters only after a new positive cycle or explicit boundary.
- [ ] Prevent collector refresh and lifecycle refresh from issuing duplicate API calls for the same account within one scheduler pass.
- [ ] Add tests for delayed dashboard data, usage increasing while status is stale, and banned after boundary.

## Task 5: Chrome Token Expiry and Opt-in Automatic Login

**Files:**
- Modify: `contrib/chrome-provider-importer/background.js`
- Modify: `contrib/chrome-provider-importer/popup.js`
- Modify: `contrib/chrome-provider-importer/popup.html`
- Modify: `contrib/chrome-provider-importer/manifest.json`
- Modify: `app/routers/earnapp_accounts.py`
- Modify: `app/static/js/app.js`
- Test: `tests/test_chrome_provider_importer.py`, `tests/test_earnapp_account_routes.py`

- [ ] Keep one explicit Chrome/GPM profile bound to one EarnApp account.
- [ ] Record expiry metadata with source `jwt`, `cookie`, or `unknown`; never claim opaque token expiry is known.
- [ ] Remove unconditional 15-minute sync alarm. Keep cookie-change debounce and explicit “Sync now”.
- [x] Add extension setting `autoLoginEnabled`, default false; enable only after operator checks it.
- [ ] Add an event-driven refresh flow: server marks `needs_token_refresh`; extension, only when enabled, opens the already-bound EarnApp profile, performs `Settings -> logout`, then login flow, waits for dashboard success, imports new cookies, and reports result.
- [ ] Do not automate CAPTCHA/2FA; pause and show operator action required.
- [ ] Add server-side one-time nonce/state to prevent importing a different account into a bound profile.
- [ ] Add visible states: token expired, auth failed, login required, sync succeeded, sync blocked by operator.
- [ ] Add tests for no periodic sync, cookie-change sync, expiry source, profile/account mismatch, and manual-login fallback.

## Task 6: Reference VPS Runtime Clone for Three OS

**Files:**
- Modify: `app/earnapp_runtime.py`
- Modify: `app/earnapp_identity.py`
- Modify: `scripts/build_earnapp_canary_image.py`
- Modify: `services/bandwidth/earnapp.yml`
- Test: `tests/test_earnapp_canary_contract.py`, `tests/test_earnapp_identity.py`, `tests/test_earnapp_runtime_policy.py`
- Evidence: preserve reference material under `earnapp_update_05092026` and `.tmp-reference-mac/`

- [x] Read-only inventory reference VPS runtime, binary, entrypoint, sidecar, fake proxy, watchdog, environment, labels, and restart policy for macOS/iOS/Ubuntu.
- [x] Build a sanitized reference manifest containing binary/script hashes, container limits, mounts, bridge/LAN addressing, capabilities and restart policy for each OS: `docs/evidence/earnapp/reference-vps-2026-09-08.md`.
- [x] Diff reference bundle metadata against CashPilot without copying UUID, account, volume, proxy, or credentials; emit `reference-bundle-manifest-2026-09-08.json`.
- [x] Port only missing behavior after an exact per-OS contract diff: verified upgraded image digests and artifact hashes; no UUID, profile, proxy credential, or host fingerprint copied.
- [ ] Gate every image build on a sanitized fidelity report for macOS/iOS/Ubuntu covering binary/image digest, entrypoint, supervisor/watchdog, `lan_ip`, interface selection, redsocks/iptables, DNS, proxy bypasses, link retry/cooldown, mounts, limits, capabilities and restart policy.
- [x] Ensure all three platforms use Docker; remove accidental LXD selection without touching unrelated providers.
- [ ] Add tests for identity uniqueness, platform contract, proxy egress, watchdog and reboot persistence.

## Task 7: Remove Kernel/Runtime Fingerprints

**Files:**
- Modify: platform boot/entrypoint scripts discovered under `app/earnapp_runtime.py` and runtime assets
- Test: `tests/test_earnapp_runtime_policy.py`

- [ ] Inventory every uname field sent by each binary.
- [ ] Supply complete profile-controlled `uname_r`, `os_version`, hostname, machine-id, serial, arch, model and interface metadata.
- [ ] Prevent direct leakage of host kernel `Linux 6.17.0-1022-azure` where the binary contract permits spoofing.
- [ ] Do not claim kernel spoofing where Docker cannot alter a kernel-visible syscall; instead fail verification or document the remaining field.
- [ ] Verify network egress and metadata from inside each container.

## Task 8: Private GHCR Release

**Files:**
- Modify: `scripts/build_earnapp_canary_image.py`
- Modify: `.github/workflows/` relevant EarnApp workflow
- Modify: `docs/guides/earnapp.md`
- Test: CI contract tests

- [ ] Read GHCR credentials only from the supplied local secret file; never commit or print them.
- [ ] Build separate pinned images for macOS, iOS and Ubuntu with SBOM/provenance if available.
- [ ] Push private GHCR tags and record immutable digests in runtime config.
- [ ] Worker pull uses scoped read-only package credentials, not a global token.
- [ ] Verify clean host pull, digest match, restart persistence, and no secret in image layers/logs.

## Task 9: Canary, Audit, Release

**Files:**
- Modify: `docs/guides/earnapp.md`
- Create: `docs/evidence/earnapp/2026-09-08-production-canary.md`

- [ ] Clean only non-protected EarnApp test runtimes on the reference/test VPS; preserve operator-owned scheduler behavior.
- [ ] Reboot worker and verify baseline before deploy.
- [ ] Create six fresh nodes, two macOS, two iOS, two Ubuntu, each with a distinct eligible proxy and fresh identity.
- [ ] Verify remote device creation, country, Earnings Update boundary, positive usage, proxy egress, DNS fail-closed, heartbeat, restart, banned recovery simulation, token warning and reboot persistence.
- [ ] Run focused tests, full regression suite, image digest audit, secret scan and git diff audit.
- [ ] Commit, open PR, review, merge, release, redeploy only EarnApp runtime/UI paths, then recheck.
- [ ] Mark EarnApp production-ready only after all evidence is recorded.

## Review Gate Before Resume

- [ ] Confirm whether automatic login may navigate only the already-bound EarnApp profile and must stop for CAPTCHA/2FA.
- [ ] Confirm account suspended/locked release occurs after local cleanup acknowledgement, not before.
- [ ] Confirm remote device deletion is mandatory before every banned/proxy replacement; uncertain deletion remains `RECOVERY_HOLD`.
- [x] Confirm production canary means exactly two fresh nodes per OS on `vps-test-us` after clean/reboot.
