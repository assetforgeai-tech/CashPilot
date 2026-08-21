# Platform Baseline: Wallet, Proxy Pool, Settings và Fleet

Ngày rà soát: 2026-08-22

Commit source được đối chiếu: `082b947ebdae31e9e0ced9eef76d5e53c9f16da6`

Tài liệu này bổ sung baseline vận hành cho các subsystem dùng chung. Đây là tài liệu đọc hiểu, không phải ủy quyền thay đổi code hoặc live state. Mọi provider hiện hành, bao gồm Mysterium direct-only, là `PROTECTED_DONE`; Grass đã bị loại khỏi product.

## 1. MYST Wallet

**Current MYST lane: direct-only.** MYST is not a Proxy Pool provider in the current contract. `app/provider_runtime.py` exposes only `direct`, `tests/test_provider_modes.py` asserts `{"direct"}`, and `tests/test_deploy_modes_api.py` rejects proxy mode. Historical proxy experiments and old Git commits are not current deployment guidance.

MYST Wallet là asset inventory riêng, không phải proxy pool và không được gộp với wallet của provider khác. Các ghi chú Grass trong history không phải current contract.

**Lifecycle chuẩn:** import wallet mã hóa → fingerprint/address → funding/quarantine state → exclusive lease theo worker/client/public IP → materialize keystore và runtime state → worker heartbeat/provider evidence → release/reclaim hoặc stale-worker reconciliation.

**Invariants cần bảo vệ:**

- Khi lưu at rest, raw wallet chỉ tồn tại trong inventory được mã hóa; không gửi trong heartbeat, logs hoặc graph artifacts.
- Lease có assignment version và optimistic checks; không release wallet của assignment mới bằng stale worker event.
- Identity, wallet address, client instance và public IP phải nhất quán qua restart hợp lệ.
- `Registered` không đồng nghĩa earning; cần TUN, `NET_ADMIN`, WireGuard active và traffic/session evidence.
- Funding không được tự suy diễn thành `Registered` khi CLI/API trả trạng thái không đọc được.

**Evidence cần có trước khi chốt:** funded lease đúng, persistence sau restart, registration sync, dashboard identity, traffic capability và transition release/reclaim/quarantine. Canary phải dùng wallet riêng.

Evidence chính: `app/myst_wallets.py`, `app/myst_runtime.py`, `app/worker_api.py`, `tests/test_myst_wallets_module.py`, `tests/test_worker_myst_sync.py`, `docs/configuration.md`.

## 2. NKN Wallet

NKN Wallet hiện là inventory/admin surface riêng, không phải provider trong catalog 14 provider và chưa có deploy/worker runtime integration. Git history xác nhận các thay đổi tạo wallet pool và import từ folders (`6d88c0d`, `4442254`), nhưng không được suy ra NKN có lifecycle hoàn chỉnh như MYST.

**Source contract hiện có:** import folder/ZIP; validate `wallet.json` + `wallet.pswd`; lưu wallet material mã hóa; deduplicate theo folder/fingerprint; owner-only API/UI để import và list inventory. Schema có các cột dự phòng cho lease/runtime state, nhưng repo chưa có NKN lease/release, deploy attach, heartbeat sync hoặc runtime evidence flow. Sự tồn tại của cột không phải bằng chứng tính năng đã hoạt động.

**Baseline cần giữ:** bảo toàn encryption, import validation, uniqueness và owner authorization. Không dùng MYST wallet lease hoặc proxy lease để đại diện cho NKN; cũng không gán trạng thái provider cho NKN khi chưa có catalog/runtime contract.

**Khoảng bằng chứng hiện tại:** chưa có live inventory snapshot, và source hiện tại chưa cung cấp runtime contract để có thể tuyên bố completion về assignment, funding, persistence hoặc heartbeat. Mọi mở rộng NKN phải là feature riêng có impact map và approval.

## 3. Proxy Pool

Proxy Pool cung cấp worker-level egress qua sing-box. Provider direct không tự động nhận proxy lease nếu catalog không yêu cầu.

**Lifecycle:** inventory → health/live probe → assignment → exit-IP verification → heartbeat reconciliation → dead-lease release → reassignment/rotation → restart chỉ egress component bị ảnh hưởng.

**Invariants:**

- Lease khỏe không được rotate chỉ vì muốn chuẩn hóa.
- Dead lease phải được loại khỏi assignment trước khi cấp lại.
- Probe phải phân biệt endpoint reachability và exit IP; IP cũ/mismatch là evidence lỗi.
- Rotation không được làm mất provider volume, identity, credential hoặc wallet assignment.
- Một worker-level proxy change có thể ảnh hưởng nhiều provider; phải lập impact map trước mutation.

Evidence chính: `app/database.py`, `app/routers/proxies.py`, `app/proxy_egress.py`, `app/worker_api.py`, proxy lease tests, `docs/configuration.md`, `docs/ACTIVE_CONTEXT.md`.

## 4. Settings

Settings/database là source of truth cho runtime policy, provider credentials, collector/session credentials, proxy policy, MYST default password và auto-deploy policy. `CASHPILOT_*` environment variables chủ yếu cấu hình bootstrap, network và worker process.

**Precedence và an toàn:**

- Bootstrap/env không được âm thầm ghi đè secret đã lưu trong Settings.
- Credential deploy thay đổi có thể đánh dấu provider `needs_redeploy`; collector/session-only credential không được tự recreate container.
- Secrets write-only, không trả plaintext về browser, logs, heartbeat hoặc artifacts.
- Settings mutation phải qua authenticated UI/API; không sửa trực tiếp database.
- Auto-deploy là opt-in, chờ healthy heartbeats và chạy tuần tự theo worker policy.

Evidence chính: `docs/configuration.md`, `docs/getting-started.md`, Settings routes/templates, credential regression tests và `docs/research/provider-end-to-end-normalization-plan-2026-08.md`.

## 5. Fleet

Fleet gồm UI/server registry và các worker Docker. Worker enroll bằng shared bootstrap key, sau đó nhận per-worker key; heartbeat định kỳ mang container list, system info và `provider_states`.

**Lifecycle:** bootstrap/enroll → per-worker key issuance → heartbeat → online/stale/offline classification → command dispatch → version/evidence reconciliation → re-enroll hoặc retire.

**Invariants:**

- Worker identity dựa trên stable `client_id`; key không được dùng để impersonate worker khác.
- Worker offline không được tự động xóa lịch sử, provider state hoặc volume.
- Worker URL phải qua SSRF/range validation trước command dispatch.
- Version hiển thị phải phản ánh image đang chạy, không chỉ tag được khai báo.
- Fleet-level deploy/upgrade có blast radius lớn hơn một provider; không bulk-redeploy trong giai đoạn baseline.

Evidence chính: `docs/fleet.md`, `docs/architecture.md`, `docs/upgrade-v1.md`, `app/worker_api.py`, `app/fleet_key.py`, `.github/workflows/test.yml`.

## 6. Impact map và quyền thay đổi

| Subsystem | Có thể ảnh hưởng | Baseline action |
|---|---|---|
| MYST Wallet | Mysterium, database, worker heartbeat | Chỉ canary wallet riêng |
| NKN Wallet | Database và owner admin UI hiện tại; runtime tương lai nếu được bổ sung | Bảo toàn inventory; không tuyên bố lease/runtime đã có |
| Proxy Pool | Nhiều provider trên cùng worker | Không rotate lease khỏe |
| Settings | Mọi provider nếu credential/policy dùng chung | Phân biệt deploy credential và collector credential |
| Fleet | Toàn bộ worker/provider trên fleet | Không bulk upgrade/redeploy |

Trước mọi thay đổi shared module phải có call/data-flow, provider impact map, regression tests, canary riêng, rollback giữ nguyên identity/volume/credential/lease và xác nhận rõ ràng của người dùng.

## 7. Rà soát khoảng trống còn lại

Sau khi bổ sung tài liệu này, các nội dung nền tảng còn thiếu hoặc chưa đủ bằng chứng là:

1. **NKN Wallet boundary:** chưa có live inventory snapshot; repo cũng chưa có active provider, lease/release hoặc worker runtime flow để kiểm chứng completion.
2. **MYST live completion:** chưa có bằng chứng live đầy đủ cho funded lease + Registered + TUN/WireGuard traffic + dashboard identity.
3. **Proxy Pool live matrix:** chưa có bảng mapping hiện tại giữa từng worker, lease, exit IP và provider impact; không được tự thu thập bằng mutation.
4. **Settings credential audit:** chưa có inventory không lộ secret chứng minh mọi provider đã phân biệt deploy credential với collector/session credential.
5. **Fleet current-state snapshot:** tài liệu mô tả contract tốt, nhưng cần snapshot read-only về worker/client_id/version/heartbeat/offline history trước rollout tương lai.
6. **NKN product decision:** chưa có quyết định riêng về việc giữ inventory-only, hoàn thiện runtime hay retire surface này; không tự suy diễn từ schema dự phòng.

Các khoảng trống trên chỉ được ghi nhận; không tự sửa, deploy, rotate lease, migrate database hoặc thay đổi provider baseline. Read-only audit tại commit `082b947` xác nhận đây vẫn là các khoảng trống live, không phải lỗi đã được giải quyết bằng source-only evidence.
