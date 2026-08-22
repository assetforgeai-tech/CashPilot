# CashPilot: Repo và GitHub Understanding

Ngày chụp trạng thái: 2026-08-22

Commit được phân tích: `082b947ebdae31e9e0ced9eef76d5e53c9f16da6`

## Phạm vi và nguyên tắc

Tài liệu này tổng hợp kết quả đọc source, tests, docs, Git history và GitHub metadata bằng `gh`. Giai đoạn phân tích không sửa product source, không truy cập hoặc thay đổi VPS, container, volume, database, credential, proxy lease, wallet lease hay provider identity.

Tất cả 14 provider hiện hành là baseline bất biến. Grass đã bị loại khỏi product theo quyết định ghi tại `provider-removal-grass-2026-08.md`; Mysterium vẫn direct-only. Phát hiện lịch sử chỉ có giá trị tham khảo; không được dùng làm lý do refactor hoặc redeploy khi chưa có phê duyệt rõ ràng.

## Snapshot Git và GitHub

| Hạng mục | Trạng thái đã kiểm chứng |
|---|---|
| Canonical base branch | `main`, theo dõi `origin/main` |
| Audited base HEAD | `082b947`, khớp `origin/main` trước branch tài liệu này |
| Fork | `assetforgeai-tech/CashPilot` |
| Upstream | `GeiserX/CashPilot` |
| Divergence | Fork ahead 331, behind 26; histories diverged |
| Fork release mới nhất | `v1.1.1` |
| Upstream release quan sát | `v1.36.2` |
| Fork CI tại HEAD | Documentation, Tests, Catalog Check, CodeQL và Lint thành công; deploy job skipped |
| Audit worktree | Branch `docs/refresh-read-only-baseline-2026-08-22`; chỉ có thay đổi Markdown, local Understand artifacts được ignore |

Upstream mới hơn không đồng nghĩa fork phải merge. Fork-only history chứa nhiều contract quan trọng về provider/runtime hardening, Grass identity/auth, MYST wallet lease/runtime, proxy lease rotation và CI/release. Mọi merge hoặc cherry-pick phải được đánh giá riêng và nằm ngoài giai đoạn này.

## Kiến trúc và luồng triển khai

CashPilot gồm FastAPI UI/server, worker API, persistence layer, service catalog YAML, Docker orchestration, collectors và CI/release workflows.

Luồng deploy bắt đầu từ API/UI, resolve service catalog và deploy mode, chuẩn hóa instance slug/credential, cấp resource lease nếu provider yêu cầu, rồi gửi request tới worker. Worker dựng Docker configuration, volume, labels và runtime state; provider automation thực hiện các bước đặc thù sau container start. Heartbeat và provider evidence đưa trạng thái runtime về server để đồng bộ database và UI.

Proxy lifecycle hiện dùng server-authoritative, worker-ACK rotation. Server probe pool và chọn candidate nhưng không đổi lease trước; worker probe candidate từ chính VPS, stage config vào named volume `/etc/sing-box`, validate toàn bộ sidecar, restart riêng các sidecar liên quan rồi trả ACK đã redacted gồm binding token, proxy ID, observed exit IP, instance list và config hash. Server serialize các proxy-assignment transaction và chỉ CAS-commit `proxy_assignments` cùng `provider_instances` sau ACK hợp lệ. Assignment generation cũ, candidate vừa bị worker khác giữ hoặc mixed proxy rows trên cùng worker làm flow fail closed và worker rollback config cũ. Nếu response apply bị mất, server thử rollback theo binding token vì worker có thể đã restart thành công. Nếu CAS đã thành công nhưng confirm cleanup thất bại, DB/runtime vẫn cùng candidate; chỉ cleanup backup còn pending, không rollback DB mù quáng.

Giới hạn phase này là assignment vẫn ở worker-level để giữ compatibility. Target topology dài hạn là `(worker, public_ip_slot, provider, instance)`, cần cho Pawns private binding và VPS nhiều public IPv4. Legacy sidecar chưa có persistent config volume fail closed; không bulk redeploy provider đã `PROTECTED_DONE`. MYST và NKN là direct-only nên không tham gia Proxy Pool.

Release workflow dùng diff từ tag trước để quyết định có tạo release hay không. Khi có release, workflow tạo version, chạy gate tests, build và publish cả UI lẫn worker lên GHCR, xác minh image/tag rồi mới tạo Git tag và GitHub release. Fork `v1.1.1` là release hiện tại; tag trỏ tới `78edd1b` và release này có cả hai fork image. Việc release không tự đồng nghĩa deploy.

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
| `grass` | `RETIRED` | Không còn catalog/runtime; giữ legacy rows/secrets để tương thích |
| `mysterium` | `PROTECTED_DONE` | Direct-only; không đưa vào Proxy Pool |

## Retired Grass history

Các experiment, dashboard observations và quota diagnostics cũ chỉ còn giá trị audit trong Git history và dated research. Chúng không phải deployment guidance hiện hành. Product-removal boundary, legacy-data policy và verification được định nghĩa tại `provider-removal-grass-2026-08.md`.

## Mysterium (current contract: direct-only)

MYST có inventory riêng trong `myst_wallets`, lưu raw wallet mã hóa cùng funding, quarantine, lease và runtime state. Current provider contract là **direct-only**, không dùng Proxy Pool. Server cấp exclusive funded-wallet lease theo worker/client/public IP và assignment version. Worker materialize keystore/state, restart container, unlock identity, áp MMN key và start WireGuard; heartbeat chỉ gửi metadata an toàn, không gửi raw wallet.

Registration được đọc từ `myst cli identities get` và đồng bộ có điều kiện. `Registered` chưa đủ chứng minh earning: runtime phải có `/dev/net/tun`, capability `NET_ADMIN`, WireGuard active và traffic/session evidence. Dashboard/collector phải resolve đúng node identity.

Điều kiện chốt MYST direct là funded wallet lease đúng và bền qua restart hợp lệ, registration và assignment sync đúng, TUN/WireGuard có traffic evidence, dashboard nhận đúng identity, secret không bị lộ, và các transition release/reclaim/quarantine/funding được xác nhận bằng canary riêng. Không cần proxy lease; public IP direct là conflict boundary riêng.

## Gate cho thay đổi tương lai

Mọi provider hiện hành đều là baseline bảo vệ. Nếu buộc phải sửa shared module, cần impact map, danh sách provider có thể bị ảnh hưởng, regression tests cho shared contracts, canary riêng, rollback bảo toàn identity/volume/credential/lease và phê duyệt rõ ràng của người dùng.

## Read-only audit artifacts

Read-only audit ngày 2026-08-21/22 đã xác nhận knowledge graph 1.563 nodes,
domain graph 63 nodes và coverage 301/301 files tại commit `082b947`. Các graph
và báo cáo chi tiết nằm trong local ignored directory `.understand-anything/`;
chúng không phải runtime state và không thay thế live verification.
