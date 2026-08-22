# CashPilot: Repo và GitHub Understanding

Ngày chụp trạng thái: 2026-08-23

Commit được phân tích: `4c55eac762dc375d1381cab42a902ec21796793f`

## Phạm vi và nguyên tắc

Tài liệu này tổng hợp kết quả đọc source, tests, docs, Git history và GitHub metadata bằng `gh`. Giai đoạn phân tích không sửa product source, không truy cập hoặc thay đổi VPS, container, volume, database, credential, proxy lease, wallet lease hay provider identity.

14 provider cũ đã chốt là baseline bất biến; NKN direct-only cũng đã chuyển sang
`PROTECTED_DONE` sau canary trên `test-sing`. Grass đã bị loại khỏi product theo
quyết định ghi tại `provider-removal-grass-2026-08.md`; Mysterium vẫn
direct-only. Phát hiện lịch sử chỉ có giá trị tham khảo; không được dùng làm lý
do refactor hoặc redeploy khi chưa có phê duyệt rõ ràng.

## Snapshot Git và GitHub

| Hạng mục | Trạng thái đã kiểm chứng |
|---|---|
| Canonical base branch | `main`, theo dõi `origin/main` |
| Audited base HEAD | `4c55eac`, merge PR #13, khớp `origin/main` |
| Fork | `assetforgeai-tech/CashPilot` |
| Upstream | `GeiserX/CashPilot` |
| Divergence | Fork ahead 343, behind 26; histories diverged |
| Fork release mới nhất | `v1.3.2` |
| Upstream release quan sát | `v1.36.2` |
| Fork CI/release hiện tại | PR #13 pass Analyze/CodeQL, Ruff và Tests; commit `4c55eac` pass CodeQL, Lint, Catalog Check, Tests và Auto Release |
| Merge/release state | PRs #10-#13 đã merge; `v1.3.2` có UI/worker image manifests và Auto Release thành công |
| Tag namespace | Fork tags được giữ ở `refs/fork-tags/*`; không lấy local `refs/tags/*` làm bằng chứng vì upstream dùng trùng version names |
| Audit worktree | Branch `docs/nkn-live-canary`; chỉ cập nhật tài liệu/evidence, `site/` untracked có trước và được giữ nguyên |

Upstream mới hơn không đồng nghĩa fork phải merge. Fork-only history chứa nhiều contract quan trọng về provider/runtime hardening, Grass identity/auth, MYST wallet lease/runtime, proxy lease rotation và CI/release. Mọi merge hoặc cherry-pick phải được đánh giá riêng và nằm ngoài giai đoạn này.

## Kiến trúc và luồng triển khai

CashPilot gồm FastAPI UI/server, worker API, persistence layer, service catalog YAML, Docker orchestration, collectors và CI/release workflows.

Luồng deploy bắt đầu từ API/UI, resolve service catalog và deploy mode, chuẩn hóa instance slug/credential, cấp resource lease nếu provider yêu cầu, rồi gửi request tới worker. Worker dựng Docker configuration, volume, labels và runtime state; provider automation thực hiện các bước đặc thù sau container start. Heartbeat và provider evidence đưa trạng thái runtime về server để đồng bộ database và UI.

Proxy lifecycle hiện dùng server-authoritative, worker-ACK rotation. Server probe pool và chọn candidate nhưng không đổi lease trước; worker probe candidate từ chính VPS, stage config vào named volume `/etc/sing-box`, validate toàn bộ sidecar, restart riêng các sidecar liên quan rồi trả ACK đã redacted gồm binding token, proxy ID, observed exit IP, instance list và config hash. Server serialize các proxy-assignment transaction và chỉ CAS-commit `proxy_assignments` cùng `provider_instances` sau ACK hợp lệ. Assignment generation cũ, candidate vừa bị worker khác giữ hoặc mixed proxy rows trên cùng worker làm flow fail closed và worker rollback config cũ. Nếu response apply bị mất, server thử rollback theo binding token vì worker có thể đã restart thành công. Nếu CAS đã thành công nhưng confirm cleanup thất bại, DB/runtime vẫn cùng candidate; chỉ cleanup backup còn pending, không rollback DB mù quáng.

Giới hạn phase này là assignment proxy vẫn ở worker-level để giữ compatibility. NKN dùng topology riêng `(worker, public_ip_slot, wallet, instance)` và không tham gia Proxy Pool. Legacy sidecar chưa có persistent config volume fail closed; không bulk redeploy provider đã `PROTECTED_DONE`. MYST và NKN là direct-only.

Release workflow dùng diff từ tag trước để quyết định có tạo release hay không. Khi
có release, workflow chạy gate tests, build và publish độc lập UI/worker lên GHCR,
xác minh image/tag rồi mới tạo Git tag và GitHub release. Release `v1.3.2` đã
publish UI digest `sha256:25450f...302f31e` và worker digest
`sha256:e487e8...87a28`; live deployment vẫn là thao tác riêng có approval.

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
| `nkn` | `PROTECTED_DONE` | Direct-only; giữ nguyên contract và canary thành công |

## Retired Grass history

Các experiment, dashboard observations và quota diagnostics cũ chỉ còn giá trị audit trong Git history và dated research. Chúng không phải deployment guidance hiện hành. Product-removal boundary, legacy-data policy và verification được định nghĩa tại `provider-removal-grass-2026-08.md`.

## Mysterium (current contract: direct-only)

MYST có inventory riêng trong `myst_wallets`, lưu raw wallet mã hóa cùng funding, quarantine, lease và runtime state. Current provider contract là **direct-only**, không dùng Proxy Pool. Server cấp exclusive funded-wallet lease theo worker/client/public IP và assignment version. Worker materialize keystore/state, restart container, unlock identity, áp MMN key và start WireGuard; heartbeat chỉ gửi metadata an toàn, không gửi raw wallet.

Registration được đọc từ `myst cli identities get` và đồng bộ có điều kiện. `Registered` chưa đủ chứng minh earning: runtime phải có `/dev/net/tun`, capability `NET_ADMIN`, WireGuard active và traffic/session evidence. Dashboard/collector phải resolve đúng node identity.

Điều kiện chốt MYST direct là funded wallet lease đúng và bền qua restart hợp lệ, registration và assignment sync đúng, TUN/WireGuard có traffic evidence, dashboard nhận đúng identity, secret không bị lộ, và các transition release/reclaim/quarantine/funding được xác nhận bằng canary riêng. Không cần proxy lease; public IP direct là conflict boundary riêng.

## NKN (current contract: direct-only)

NKN dùng `nknorg/nkn:latest` và không tham gia Proxy Pool. Bootstrap phát hiện
public IPv4 slot, dựng bridge/SNAT và giới hạn file; server lease một wallet
riêng theo `(worker, slot)` rồi worker tạo volume/container tuần tự. Heartbeat
chỉ gửi node identity, trạng thái runtime và `getnodestate` đã redacted. Node
chỉ online khi container đang chạy và RPC trả `PERSIST_FINISHED`.

Canary `test-sing` đã xác minh beneficiary Settings, wallet lease/version,
bridge/ports/resource/restart policy, worker heartbeat HTTP 200 và collector
balance. Node đạt `PERSIST_FINISHED` mà không đổi container/node identity;
worker heartbeat đồng bộ `online=true`, Fleet báo `total_nodes=1`, `online=1`,
`offline=0`, và wallet `1` vẫn giữ assignment version `3`. NKN vì vậy là
`PROTECTED_DONE`.

## Gate cho thay đổi tương lai

Mọi provider hiện hành đều là baseline bảo vệ. Nếu buộc phải sửa shared module, cần impact map, danh sách provider có thể bị ảnh hưởng, regression tests cho shared contracts, canary riêng, rollback bảo toàn identity/volume/credential/lease và phê duyệt rõ ràng của người dùng.

## Trạng thái hiện tại sau PR #13

- Proxy rotation hiện có contract server-authoritative/worker-ACK: worker probe
  candidate từ chính VPS, stage persistent sing-box config, restart sidecar liên
  quan và trả ACK đã redacted; server chỉ CAS-commit assignment sau ACK hợp lệ.
- Custom probe targets do request cung cấp bị từ chối trước network access; đây là
  guard chống SSRF, có regression test và CodeQL đã xác nhận.
- Generic proxy assignment vẫn worker-level để bảo toàn compatibility. NKN là
  ngoại lệ direct-only có topology `(worker, public_ip_slot, wallet, instance)`;
  không được dùng ngoại lệ này để refactor provider protected.
- NKN canary đã hoàn tất và trở thành baseline bảo vệ. Giữ nguyên node/volume/
  lease thành công; mọi thay đổi NKN hoặc shared module sau này cần impact map,
  canary riêng và approval mới.

## Read-only audit artifacts

Read-only audit ngày 2026-08-21/22 đã xác nhận knowledge graph 1.563 nodes,
domain graph 63 nodes và coverage 301/301 files tại commit `082b947`. Các graph
và báo cáo chi tiết nằm trong local ignored directory `.understand-anything/`;
chúng không phải runtime state và không thay thế live verification.
