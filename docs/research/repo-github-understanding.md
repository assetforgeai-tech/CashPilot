# CashPilot: Repo và GitHub Understanding

Ngày chụp trạng thái nền: 2026-08-23; cập nhật live EarnApp v1.13.4: 2026-08-28

Commit nền hiện tại là `8d2b860` (merge PR #52, `origin/main`, tag
`v1.13.4`). Worktree closeout chỉ thay đổi tài liệu sau khi product source,
release và live gates đã được xác minh.

## EarnApp platform canary investigation (2026-08-28)

The v1.13.4 recovery/rotation closeout remains the immutable baseline for the
two existing Docker nodes, but platform closeout is reopened for fresh
disposable canaries. An authenticated usage read shows node 1 has positive
current-day qualified usage (`32,740,937 ms`), while node 2 has only `18,142 ms`
and is near plateau. Both are online and not banned. The earlier statement that
both nodes had zero current-day usage was caused by selecting the wrong usage
series value and is withdrawn.

This evidence does not prove Docker is the root cause. Node 1 has repeated WSS
timeouts and proxy `502` responses; node 2 has a clean route but little
workload, so control-plane allocation/eligibility remains an open hypothesis.
The next safe lanes are a new iOS Docker node on a VN residential proxy and a
new official Ubuntu LXD node on a non-VN residential proxy. Existing containers,
sidecars, volumes, identities, account bindings and leases are not migration
targets. MacOS/iOS remain Docker-only; Ubuntu is the only EarnApp LXD lane.

## EarnApp v1.13.4 recovery/rotation closeout (2026-08-28)

- PR #52 sửa đúng root cause Docker network namespace: main EarnApp dùng
  `container:<sidecar-id>` phải được restart sau sidecar apply/rollback để gắn
  namespace mới. CI và Auto Release run `33137032952` pass; worker digest là
  `sha256:9e8e3e20f671fd775aa4443ba9d0b63b11fcb90bb63a96cb549213f9ed7e695f`.
- Chỉ worker `43406` trên `test-sing` được recreate `--no-deps`; worker identity
  và key hash không đổi. NKN, MYST và mọi provider protected khác không bị
  restart/redeploy. Server UI chủ đích giữ v1.13.2 vì fix chỉ chạy trong worker.
- Node protected `earnapp-canary-test-sing-1` giữ nguyên container, sidecar,
  volume, device, lease `12706`, egress `171.251.97.103`, machine ID và lifecycle.
- Canary riêng `earnapp-recovery-test-sing-2` giữ nguyên container, volume,
  account, generation, device và machine ID qua hai rotation CAS:
  `12708/116.98.176.124 -> 12724/14.236.137.88 -> 12708/116.98.176.124`.
  Lần hai chứng minh prior-proxy affinity; main giữ `eth0`, route, DNS và egress.
- Authenticated account evidence thấy cả hai device online/not-banned; snapshot
  online `2`, offline `0`, balance `$2.284`. DB `integrity=ok`, FK `0`, active
  reservation `0`, active EarnApp lease `2`.
- EarnApp được nâng thành `PROTECTED_DONE`. Mọi thay đổi tương lai phải có impact
  map, regression coverage, canary mới và approval rõ ràng.

## EarnApp v1.13.2 scoped live verification (2026-08-28)

- PRs #46-#48 đã merge phần standardization, Docker egress decoding và legacy
  state hydration. PR #48 merge tại
  `ba2d29dda746327e0db445239244e12c684d9e03`; các check sau merge gồm Catalog,
  CodeQL, Lint, Tests và Auto Release đều thành công. Release `v1.13.2` được
  publish từ cùng merge commit.
- Registry trả UI digest
  `sha256:83a5b98c698d4ac59513d72108d516581e58be2895dcf9351ee68d77fc8ce913`
  và worker digest
  `sha256:03419892ec982acb240d13b6238bbb9a6ea15f36ff1db281d39e8fb20a73e1a7`.
  Backup trước deploy nằm tại
  `/opt/cashpilot/backups/earnapp-v132-authority-backfill-20260827T192358Z`.
- Legacy metadata thiếu authority được CAS-fill sau khi đối chiếu database,
  lease, proxy evidence, encrypted spec và container labels:
  `platform=macos`, `expected_egress_ip=171.251.97.103`. Không đổi account,
  worker, generation, device identity hoặc proxy lease.
- Chỉ `cashpilot-ui` trên server và `cashpilot-worker` trên `test-sing` được
  force-recreate riêng, không kéo dependency. Cả hai healthy ở version `1.13.2`;
  SQLite là schema `21`, `integrity=ok`, foreign-key violation `0`.
- Worker row `43406` giữ client ID
  `e2a103a007d7e7c93172de6505e2e14839519dca4176989561dcf6f827a0871c`;
  signing-key file được xác minh không đổi nhưng secret value không được ghi vào
  tài liệu. Heartbeat authenticated mới được nhận lúc
  `2026-08-27 19:30:18 UTC` và `2026-08-27 19:31:21 UTC`.
- Logical node `earnapp-canary-test-sing-1` vẫn thuộc Account Pool id `2`
  (`assetforgeai`), platform/backend `macos`/`docker`, lease `#12706`, egress
  `171.251.97.103`. Container, sidecar, volume, account binding, generation và
  device identity đều được giữ nguyên; Fleet báo online `1`, offline `0`.
- Chrome profile 40 là nguồn authoritative: account `AssetForge AI`, balance
  `$2.284`, device `sdk-mac-4ae944b1`, country `VN`, usage đang hoạt động.
- NKN LXD, Mysterium và các provider `PROTECTED_DONE` khác không bị thay đổi.
  Tại checkpoint v1.13.2, EarnApp vẫn chưa là `PROTECTED_DONE`; trạng thái mở đó
  đã được supersede bởi closeout v1.13.4 ở trên.

## EarnApp migration safety patch (2026-08-26)

PR #42 đã merge patch migration safety tại `a6c6e4c`; Auto Release
`32902222108` publish `v1.11.2` trỏ đúng SHA. UI-only deployment dùng digest
`sha256:31d17ca6ba17a55ae6f15686bc945a1ed12dfad29ce87f1ed71fa2ef8605086d`.
Migration/archive/marker và boot idempotency đều được xác minh live; worker và
mọi non-UI container giữ nguyên. Provider `PROTECTED_DONE`, proxy/wallet lease,
identity và volume không bị redeploy hoặc chỉnh sửa.

## EarnApp account/recovery baseline (merged 2026-08-25; historical checkpoint)

PR #40 (`102fa9e1`) bổ sung control plane cô lập cho EarnApp trên nền
`origin/main` `ff25e7b`; implementation commit là `9968a85`. PR đã merge. Việc
merge tại thời điểm đó chỉ đưa control plane vào source, chưa đồng nghĩa
official runtime, DNS, Chrome profile live hay VPS canary đã hoàn tất; provider
`PROTECTED_DONE` không bị đụng tới. Đây là mô tả lịch sử, không phải trạng thái
hiện tại.

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

Verification của baseline tại checkpoint đó đạt focused suite `283 passed`,
full non-live suite `1812 passed, 8 skipped`; migration-safety verification mới
nhất được ghi ở `docs/research/earnapp-legacy-migration-safety-2026-08.md`.

Release, registry verification và scoped UI/worker deployment đã hoàn tất ở
`v1.13.2`. Phạm vi còn mở chỉ là restart/recovery persistence và isolated proxy
rotation trên một canary mới. Global Auto Deploy phải tiếp tục
operator-disabled cho tới khi hai gate này pass. EarnApp **chưa** là
`PROTECTED_DONE`.

## Phạm vi và nguyên tắc

Tài liệu này tổng hợp kết quả đọc source, tests, docs, Git history và GitHub
metadata bằng `gh`. Phần audit kiến trúc ban đầu là read-only; phần live closeout
ở trên chỉ ghi nhận các thay đổi scoped đã được phê duyệt cho UI, worker và
EarnApp canary. Không được suy rộng bằng chứng đó thành quyền bulk redeploy.

14 provider cũ đã chốt là baseline bất biến; NKN direct-only cũng đã chuyển sang
`PROTECTED_DONE` sau canary trên `test-sing`. Grass đã bị loại khỏi product theo
quyết định ghi tại `provider-removal-grass-2026-08.md`; Mysterium vẫn
direct-only. Phát hiện lịch sử chỉ có giá trị tham khảo; không được dùng làm lý
do refactor hoặc redeploy khi chưa có phê duyệt rõ ràng.

## Snapshot Git và GitHub

| Hạng mục | Trạng thái đã kiểm chứng |
|---|---|
| Canonical base branch | `main`, theo dõi `origin/main` |
| Audited base HEAD | `ba2d29d`, merge PR #48, khớp `origin/main` và tag `v1.13.2` |
| Fork | `assetforgeai-tech/CashPilot` |
| Upstream | `GeiserX/CashPilot` |
| Divergence | Fork ahead 431, behind 31; histories diverged |
| Fork release mới nhất | `v1.13.2` (Auto Release run `33104948032`) |
| Upstream release quan sát | `v1.36.4` |
| Fork CI/release hiện tại | Commit `ba2d29d` pass CodeQL, Catalog Check, Lint, Tests và Auto Release; PR #48 đã merge |
| Merge/release state | PRs #27-#48 đã merge; `v1.13.2` đã scoped-deploy UI và worker |
| Tag namespace | Fork tags được giữ ở `refs/fork-tags/*`; không lấy local `refs/tags/*` làm bằng chứng vì upstream dùng trùng version names |
| Audit worktree | Branch `docs/earnapp-v1132-live-closeout`; chỉ cập nhật tài liệu closeout |

Upstream mới hơn không đồng nghĩa fork phải merge. Fork-only history chứa nhiều contract quan trọng về provider/runtime hardening, Grass identity/auth, MYST wallet lease/runtime, proxy lease rotation và CI/release. Mọi merge hoặc cherry-pick phải được đánh giá riêng và nằm ngoài giai đoạn này.

## Kiến trúc và luồng triển khai

CashPilot gồm FastAPI UI/server, worker API, persistence layer, service catalog YAML, Docker orchestration, collectors và CI/release workflows.

Luồng deploy bắt đầu từ API/UI, resolve service catalog và deploy mode, chuẩn hóa instance slug/credential, cấp resource lease nếu provider yêu cầu, rồi gửi request tới worker. Worker dựng Docker configuration, volume, labels và runtime state; provider automation thực hiện các bước đặc thù sau container start. Heartbeat và provider evidence đưa trạng thái runtime về server để đồng bộ database và UI.

Proxy lifecycle hiện dùng server-authoritative, worker-ACK rotation. Server probe pool và chọn candidate nhưng không đổi lease trước; worker probe candidate từ chính VPS, stage config vào named volume `/etc/sing-box`, validate toàn bộ sidecar, restart riêng các sidecar liên quan rồi trả ACK đã redacted gồm binding token, proxy ID, observed exit IP, instance list và config hash. Server serialize các proxy-assignment transaction và chỉ CAS-commit `proxy_assignments` cùng `provider_instances` sau ACK hợp lệ. Assignment generation cũ, candidate vừa bị worker khác giữ hoặc mixed proxy rows trên cùng worker làm flow fail closed và worker rollback config cũ. Nếu response apply bị mất, server thử rollback theo binding token vì worker có thể đã restart thành công. Nếu CAS đã thành công nhưng confirm cleanup thất bại, DB/runtime vẫn cùng candidate; chỉ cleanup backup còn pending, không rollback DB mù quáng.

Giới hạn phase này là assignment proxy vẫn ở worker-level để giữ compatibility. NKN dùng topology riêng `(worker, public_ip_slot, wallet, instance)` và không tham gia Proxy Pool. Legacy sidecar chưa có persistent config volume fail closed; không bulk redeploy provider đã `PROTECTED_DONE`. MYST và NKN là direct-only.

Release workflow dùng diff từ tag trước để quyết định có tạo release hay không. Khi
có release, workflow chạy gate tests, build và publish độc lập UI/worker lên GHCR,
xác minh image/tag rồi mới tạo Git tag và GitHub release. Release hiện hành được
ghi nhận ở v1.13.2; live deployment vẫn là thao tác riêng có approval.

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
| `earnapp` | `PROTECTED_DONE` | Giữ cả hai node live; thay đổi mới cần canary riêng và approval |

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

Mọi provider active đều là `PROTECTED_DONE` và là baseline bảo vệ. Nếu buộc phải
sửa shared module, cần impact map, danh sách provider có thể bị ảnh hưởng,
regression tests cho shared contracts, canary riêng, rollback bảo toàn
identity/volume/credential/lease và phê duyệt rõ ràng của người dùng.

## Lịch sử contract sau PR #13 (không phải trạng thái live hiện tại)

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
