# CashPilot: Repo và GitHub Understanding

Ngày chụp trạng thái: 2026-08-21

Commit được phân tích: `0374956a2f60a77890a78432fb7b533e480fa537`

## Phạm vi và nguyên tắc

Tài liệu này tổng hợp kết quả đọc source, tests, docs, Git history và GitHub metadata bằng `gh`. Giai đoạn phân tích không sửa product source, không truy cập hoặc thay đổi VPS, container, volume, database, credential, proxy lease, wallet lease hay provider identity.

Tất cả 14 provider hiện hành là baseline bất biến. Grass đã bị loại khỏi product theo quyết định ghi tại `provider-removal-grass-2026-08.md`; Mysterium vẫn direct-only. Phát hiện lịch sử chỉ có giá trị tham khảo; không được dùng làm lý do refactor hoặc redeploy khi chưa có phê duyệt rõ ràng.

## Snapshot Git và GitHub

| Hạng mục | Trạng thái đã kiểm chứng |
|---|---|
| Local branch | `main`, theo dõi `origin/main` |
| Local HEAD | `0374956`, khớp `origin/main` |
| Fork | `assetforgeai-tech/CashPilot` |
| Upstream | `GeiserX/CashPilot` |
| Divergence | 323 fork-only commits, 26 upstream-only commits |
| Fork release mới nhất | `v1.0.10` |
| Upstream release quan sát | `v1.36.2` |
| Fork CI tại HEAD | Auto Release, CodeQL, Lint, Action Pins, Catalog Check và Tests thành công |
| Local uncommitted trước phân tích | `docs/ACTIVE_CONTEXT.md`; graph local dưới `.understand-anything/` |

Upstream mới hơn không đồng nghĩa fork phải merge. Fork-only history chứa nhiều contract quan trọng về provider/runtime hardening, Grass identity/auth, MYST wallet lease/runtime, proxy lease rotation và CI/release. Mọi merge hoặc cherry-pick phải được đánh giá riêng và nằm ngoài giai đoạn này.

## Kiến trúc và luồng triển khai

CashPilot gồm FastAPI UI/server, worker API, persistence layer, service catalog YAML, Docker orchestration, collectors và CI/release workflows.

Luồng deploy bắt đầu từ API/UI, resolve service catalog và deploy mode, chuẩn hóa instance slug/credential, cấp resource lease nếu provider yêu cầu, rồi gửi request tới worker. Worker dựng Docker configuration, volume, labels và runtime state; provider automation thực hiện các bước đặc thù sau container start. Heartbeat và provider evidence đưa trạng thái runtime về server để đồng bộ database và UI.

Proxy lifecycle tách probe khỏi assignment. Scheduler/probe đánh giá endpoint và exit IP; lease được gắn theo worker/provider/instance. Dead lease phải được release trước khi reassignment. Một probe khỏe không phải lý do rotate lease.

Release workflow tạo version/tag, chạy gate tests, build và publish hai image UI/worker lên GHCR, xác minh tag rồi tạo GitHub release. Fork `v1.0.10` là baseline release hiện tại.

## Ma trận bảo vệ provider

| Provider | Phân loại | Quy tắc |
|---|---|---|
| `earnfm` | `PROTECTED_DONE` | Không sửa hoặc redeploy |
| `iproyal` | `PROTECTED_DONE` | Không sửa hoặc redeploy |
| `packetstream` | `PROTECTED_DONE` | Không sửa hoặc redeploy |
| `proxies-sx` | `PROTECTED_DONE` | Không sửa hoặc redeploy |
| `proxybase-xyz` | `PROTECTED_DONE` | Không sửa hoặc redeploy |
| `proxybase` | `PROTECTED_DONE` | Không sửa hoặc redeploy |
| `proxyrack` | `PROTECTED_DONE` | Không sửa hoặc redeploy |
| `repocket` | `PROTECTED_DONE` | Không sửa hoặc redeploy |
| `spide` | `PROTECTED_DONE` | Không sửa hoặc redeploy |
| `traffmonetizer` | `PROTECTED_DONE` | Không sửa hoặc redeploy |
| `urnetwork` | `PROTECTED_DONE` | Không sửa hoặc redeploy |
| `uprock` | `PROTECTED_DONE` | Không sửa hoặc redeploy |
| `wipter` | `PROTECTED_DONE` | Không sửa hoặc redeploy |
| `grass` | `REMOVED` | Không còn catalog/runtime; giữ legacy rows/secrets để tương thích |
| `mysterium` | `PROTECTED_DONE` | Direct-only; không đưa vào Proxy Pool |

## Retired Grass history

Các experiment, dashboard observations và quota diagnostics cũ chỉ còn giá trị audit trong Git history và dated research. Chúng không phải deployment guidance hiện hành. Product-removal boundary, legacy-data policy và verification được định nghĩa tại `provider-removal-grass-2026-08.md`.

## Mysterium (current contract: direct-only)

MYST có inventory riêng trong `myst_wallets`, lưu raw wallet mã hóa cùng funding, quarantine, lease và runtime state. Current provider contract là **direct-only**, không dùng Proxy Pool. Server cấp exclusive funded-wallet lease theo worker/client/public IP và assignment version. Worker materialize keystore/state, restart container, unlock identity, áp MMN key và start WireGuard; heartbeat chỉ gửi metadata an toàn, không gửi raw wallet.

Registration được đọc từ `myst cli identities get` và đồng bộ có điều kiện. `Registered` chưa đủ chứng minh earning: runtime phải có `/dev/net/tun`, capability `NET_ADMIN`, WireGuard active và traffic/session evidence. Dashboard/collector phải resolve đúng node identity.

Điều kiện chốt MYST direct là funded wallet lease đúng và bền qua restart hợp lệ, registration và assignment sync đúng, TUN/WireGuard có traffic evidence, dashboard nhận đúng identity, secret không bị lộ, và các transition release/reclaim/quarantine/funding được xác nhận bằng canary riêng. Không cần proxy lease; public IP direct là conflict boundary riêng.

## Gate cho thay đổi tương lai

Mọi provider hiện hành đều là baseline bảo vệ. Nếu buộc phải sửa shared module, cần impact map, danh sách provider có thể bị ảnh hưởng, regression tests cho shared contracts, canary riêng, rollback bảo toàn identity/volume/credential/lease và phê duyệt rõ ràng của người dùng.
