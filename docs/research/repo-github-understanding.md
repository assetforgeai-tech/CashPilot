# CashPilot: Repo và GitHub Understanding

Ngày chụp trạng thái nền: 2026-08-23; cập nhật EarnApp local: 2026-08-25

Commit nền hiện tại: `ff25e7bb1dc36b2f1ca5b7210680ce19eebe250d`

## Cập nhật EarnApp account/recovery local (2026-08-25)

Nhánh `feat/earnapp-account-recovery` bổ sung control plane cô lập cho EarnApp
trên nền `origin/main` `ff25e7b`. Thay đổi chưa commit/PR/merge/release/deploy;
không có thao tác VPS, DNS, Chrome profile, credential live hoặc provider
`PROTECTED_DONE`.

Domain model mới gồm `earnapp_accounts`, `earnapp_logical_nodes`,
`earnapp_replacement_tickets`, `earnapp_account_control_routes` và
`earnapp_account_snapshots`; schema được nâng lên `19`. Credentials được mã hóa
Fernet và API/dashboard chỉ trả metadata đã mask. Account được phân bổ theo số
logical node chưa retired thấp nhất; delete chỉ cho phép khi
`ACCOUNT_LOCKED`, yêu cầu xác nhận kép và không xóa remote device/account.

Recovery contract đã chốt là `900s` stale threshold rồi `3600s`
`RECOVERY_HOLD`. Trong một giờ hold, proxy cũ vẫn độc quyền. Hết hold, scoped
lease được release nhưng account, logical node, device ID và
`preferred_proxy_id` còn nguyên. Same-worker có thể recovery theo generation;
worker khác bắt buộc dùng one-time replacement ticket và generation/CAS để
chặn split-brain. Heartbeat cũ bị từ chối sau khi generation tăng.

Audit cuối trước PR siết thêm race boundary: ticket chỉ được tạo trong cùng
transaction khi node vẫn `RECOVERY_HOLD`/`RECOVERABLE`, generation chưa đổi và
target worker tồn tại. Heartbeat hợp lệ của worker gốc đưa node về `ACTIVE`, xóa
recovery timestamps và revoke mọi ticket chưa dùng của generation đó trong một
transaction; vì vậy ticket đã phát hành không thể claim sau khi worker gốc quay
lại. Claim cũng fail closed nếu node không còn ở recovery state.

EarnApp proxy eligibility là canonical generic-live residential egress với
latest matching-egress WSS result `CID_SET`/`eligible`. Collector luôn đi qua
route thuộc đúng account; account chưa có node dùng một control proxy riêng và
route này được transfer atomically sang node đầu tiên. Delete selected/status/
all của Proxy Pool dọn transient control-route trong cùng transaction nhưng giữ
nguyên account và encrypted credentials, tránh foreign-key failure hoặc xóa
nhầm provider state.

Manifest V3 importer dùng allowlist chính xác `auth`, `auth-method`,
`oauth-refresh-token`, `oauth-token`, `xsrf-token`, `brd_sess_id`, `cg_uuid`.
Một Chrome profile chỉ bind một EarnApp account; lần đầu phải import thủ công,
sau đó cookie change/startup/alarm 15 phút mới sync account đã bind. Sync chỉ
được gửi qua authenticated HTTPS hostname thuộc `4gmt.com`; luồng import cấu
hình của các provider khác cũng dùng cùng CashPilot origin này và không còn
quyền HTTP/IP cũ. Các collector vẫn gọi API chính chủ của provider. Importer
không đọc cookie Google/Apple và không log/hiển thị token.

Capacity và account-control allocator loại legacy assignment, active scoped
lease và active control route theo cả endpoint ID lẫn egress IP. Vì vậy một
duplicate egress chưa được đánh dấu cũng không thể bị cấp lại cho EarnApp.
Capacity dashboard đếm `DISTINCT exit_ip`, nên eligible/leaseable phản ánh số
canonical egress thật thay vì số endpoint row. Importer bắt lỗi URL CashPilot
trong UI và dùng alarm debounce riêng cho cookie change, không ghi đè alarm
đồng bộ định kỳ 15 phút.

Verification local đạt focused suite `283 passed`, full non-live suite
`1812 passed, 8 skipped`, Ruff lint, changed-file Ruff format, compileall,
JavaScript parse, deploy-baseline và `git diff --check`. Repository-wide format
check còn một lỗi baseline ở file kế hoạch cũ không đổi
`docs/superpowers/plans/2026-08-25-proxy-import-protocol.md`.

Phạm vi còn mở là catalog/runtime EarnApp chính thức, worker provision/follow/
link, MacOS/iOS emulation, Ubuntu LXD, DNS/reverse proxy cho hostname
`4gmt.com`, validation bằng Chrome profile thật và live canary. Vì vậy EarnApp
chưa được phân loại `PROTECTED_DONE`.

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
| Audited base HEAD | `ff25e7b`, merge PR #39, khớp `origin/main` |
| Fork | `assetforgeai-tech/CashPilot` |
| Upstream | `GeiserX/CashPilot` |
| Divergence | Fork ahead 343, behind 26; histories diverged |
| Fork release mới nhất | `v1.10.0` (Auto Release run `32837209953`) |
| Upstream release quan sát | `v1.36.4` |
| Fork CI/release hiện tại | Commit `ff25e7b` pass CodeQL, Catalog Check, Lint, Documentation và Tests; PR #39 đã merge |
| Merge/release state | PRs #27-#39 đã merge theo chuỗi Proxy Pool; `v1.10.0` có Auto Release thành công |
| Tag namespace | Fork tags được giữ ở `refs/fork-tags/*`; không lấy local `refs/tags/*` làm bằng chứng vì upstream dùng trùng version names |
| Audit worktree | Branch `feat/earnapp-account-recovery`; đang dirty có chủ đích với thay đổi EarnApp local chưa commit; không stage `site/` |

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
