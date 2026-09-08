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
- Với `ACCOUNT_LOCKED`, local runtime phải được xóa và lease CAS xác nhận trước khi release; remote delete chỉ best-effort sau đó. Với banned/proxy rotation, remote delete bắt buộc trước khi release/replacement.
- Không đụng provider khác hoặc protected baseline.
- Không lộ cookie, OAuth token, XSRF token, SSH key, GHCR token trong log, test output, image hoặc PR.
- Runtime/binary/image sau khi chốt phải pin digest/SHA-256; UUID, volume, credentials không clone từ reference VPS.
- Clone fidelity bắt buộc bao gồm binary, image filesystem, entrypoint, supervisor/watchdog, LAN identity/IP mapping, interface metadata, redsocks/iptables route, DNS behavior, proxy type/auth, registration, link retry, cooldown và follow; từng mục phải có hash/diff/evidence.
- Không sao chép cấu hình làm yếu TLS như `NODE_TLS_REJECT_UNAUTHORIZED=0` sang production nếu canary không chứng minh bắt buộc; nếu bắt buộc phải ghi nhận risk và giới hạn riêng cho EarnApp container.
- Token sync không chạy định kỳ vô điều kiện; chỉ chạy khi cookie thay đổi, operator bấm sync, hoặc server đánh dấu account cần refresh.
- MacOS canary dùng proxy non-VN để tách lỗi upstream VN khỏi lỗi runtime; không đổi
  hoặc rotate các node MacOS VN đang chạy.

## Current `Node recovery` Meaning

`Node recovery` hiện là lớp bảo vệ local runtime/lease khi node EarnApp mất heartbeat hoặc worker không còn container:

- `RECOVERY_HOLD` giữ logical node và proxy lease trong một khoảng thời gian để tránh reclaim nhầm khi worker vừa reboot hoặc heartbeat trễ.
- Replacement ticket giới hạn một lần thay thế, chống hai tiến trình cùng recreate một node.
- `Recreate preserves identity and does not link` nghĩa là API recreate hiện giữ device identity/volume/logical binding cũ, chỉ dựng lại runtime; nó **không** gọi EarnApp `link_device`.
- Cơ chế này phù hợp cho recovery local/offline, nhưng không đủ cho policy mới của `banned` và proxy rotation. Hai trường hợp đó phải remote-delete device rồi tạo identity/UUID/volume mới và link lại.

## Usage-flatline and Offline Policy (authoritative)

- `earnings_update_in_ms` is the account-side Earnings Update cycle boundary.
- **Usage-flatline policy:** when one Earnings Update cycle completes and the
  node's usage has not increased, restart the node in place. This is the
  required recovery action, not an advisory alert.
- At the first boundary observation, record the cycle and wait the configured grace period; do not mutate the node.
- If usage has not increased after the boundary/grace, perform exactly one `restart` for that cycle.
- The restart is in place: preserve device UUID/identity, volume, account binding, and proxy lease; do not delete or relink the remote device.
- `offline` always maps to the same in-place `restart`, even when a stale collector snapshot still contains positive usage.
- Lifecycle polling remains every 5 minutes. `last_recovery_cycle_id` prevents duplicate restarts in one Earnings Update cycle; a new boundary permits one new restart.
- Flatline/offline never triggers proxy rotation or fresh identity by itself. `banned` and unhealthy proxy remain separate replacement paths.

### Required acceptance evidence

This policy is a production gate, not an advisory heuristic:

| Signal | Decision | Preserved | Reset condition |
| --- | --- | --- | --- |
| `online=false` | restart node in place | UUID, volume, account, proxy lease | next 5-minute observation after restart |
| usage unchanged when Earnings Update reaches `0` and grace expires | restart node in place | UUID, volume, account, proxy lease | next `earnings_update_in_ms` cycle |
| usage increases before grace expires | no action | all state | clear the pending flatline marker |
| stale/unknown account snapshot | observe only | all state | fresh collector snapshot |

The scheduler must persist the cycle marker and restart marker atomically. One node receives at most one flatline restart per Earnings Update cycle. A restart must never call remote device delete, link, proxy release, or proxy rotation. These assertions require regression coverage and dated canary evidence before EarnApp is marked production-ready.

### Policy status (2026-09-08)

- [x] Usage unchanged at the completed Earnings Update boundary restarts the
  node in place after the configured five-minute observation grace.
- [x] Offline status restarts the node in place on the five-minute lifecycle
  poll, preserving identity, account binding, volume, and proxy lease.
- [x] Per-cycle marker prevents duplicate restarts; positive usage clears the
  pending flatline marker.
- [x] Focused regression suite passes: `50 passed` (`tests/test_earnapp_lifecycle.py`
  and `tests/test_earnapp_policy_matrix.py`).
- [x] Scheduler regression proves a flatline restart is suppressed after the
  recovery marker has been persisted for the same Earnings Update cycle.

### Usage-flatline policy gate (added 2026-09-08)

This is an execution policy, not merely a dashboard alert:

1. The account collector supplies `earnings_update_in_ms`; a countdown reset
   starts a new cycle marker.
2. The first boundary observation records the marker and waits five minutes.
3. If the node's effective usage is still not greater than its persisted
   baseline after that grace period, the worker performs one in-place restart.
4. The restart preserves UUID, volume, account binding, and proxy lease. It
   does not delete, relink, release, or rotate anything.
5. `last_recovery_cycle_id` suppresses duplicate restarts until the next
   Earnings Update cycle. Positive usage clears the pending boundary marker.
6. A stale or missing snapshot causes observation only; it cannot trigger a
   restart. `offline` remains a separate five-minute in-place restart path.

Acceptance evidence: `tests/test_earnapp_lifecycle.py::test_scheduler_does_not_restart_flatline_twice_in_same_earnings_cycle` plus the
focused suite above.

### MacOS non-VN isolation canary (added 2026-09-08)

- Deploy one fresh MacOS node with a new identity and one distinct eligible
  non-VN residential proxy.
- Keep the existing MacOS VN nodes unchanged; no delete, relink, lease release,
  or proxy rotation is allowed for them.
- Require the same Docker runtime contract, fail-closed egress, collector link,
  country evidence, Earnings Update boundary, and positive usage gate.
- A successful non-VN MacOS result isolates the earlier VN-country hypothesis;
  it does not by itself declare EarnApp production-ready until the normal
  usage/reboot gates pass.
- The canary deploy request now accepts `country_scope=non-vn`; the lease query
  excludes `VN` even when both country policies allow MacOS. The default remains
  `any` for backward compatibility, while production evidence must record the
  explicit scope used.

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
- [x] Test earnings boundary: one recovery decision after `earnings_update_in_ms` resets; no duplicate action during the same cycle.
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
- [x] Classify auth rejection, account suspended/locked, proxy blocked, and route failure separately.
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

- [x] Keep collector interval at 60 minutes.
- [x] Keep lifecycle interval at 5 minutes for observation and offline restart.
- [x] Persist `earnings_cycle_id`, `earnings_zero_observed_at`, `last_recovery_cycle_id`, and the previous `earnings_update_in_ms` counter.
- [x] Use account `earnings_update_in_ms` as the cycle boundary; retain the boundary marker through the positive countdown and recover once after grace.
- [x] Prevent collector refresh and lifecycle refresh from issuing duplicate API calls for the same account within one scheduler pass; lifecycle reuses a successful snapshot collected within 60 seconds while the account lock serializes concurrent callers.
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
- [x] Gate every image build on a sanitized fidelity report for macOS/iOS/Ubuntu covering binary/image digest, entrypoint, supervisor/watchdog, `lan_ip`, interface selection, redsocks/iptables, DNS, proxy bypasses, link retry/cooldown, mounts, limits, capabilities and restart policy. Reference manifest captured; `scripts/verify_earnapp_runtime_fidelity.py` now runs during context staging and fails closed on drift.
- [x] Ensure all three platforms use Docker; remove accidental LXD selection without touching unrelated providers.
- [x] Add runtime fidelity regression tests for complete and tampered contexts; live proxy egress/watchdog/reboot evidence remains in the dated canary report.

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
