# CashPilot Onboarding

## Tổng quan

CashPilot là hệ thống điều phối provider bandwidth/DePIN qua FastAPI server,
worker Docker, service catalog, resource leasing, collectors và dashboard.
Repo dùng chủ yếu Python, YAML, Docker/Compose và GitHub Actions.

Tài liệu này mô tả baseline hiện hành sau quyết định loại bỏ một provider cũ.
Chi tiết quyết định, tương thích dữ liệu cũ và bằng chứng nằm tại
`docs/research/provider-removal-grass-2026-08.md`.

## Provider matrix

- `PROTECTED_DONE`: `earnfm`, `iproyal`, `mysterium`, `packetstream`,
  `proxies-sx`, `proxybase`, `proxybase-xyz`, `proxyrack`, `repocket`,
  `spide`, `traffmonetizer`, `uprock`, `urnetwork`, `wipter`.
- Không có provider mở để redesign trong nhánh này.
- Mysterium là direct-only; không suy ra proxy mode từ lịch sử cũ.
- Dữ liệu provider đã nghỉ được giữ ở database để audit nhưng bị loại khỏi
  catalog và các current-product views.

## Các lớp kiến trúc

1. **Application/API:** entry point FastAPI, routes và UI/server behavior.
2. **Persistence/Security:** schema, migrations, encryption, credentials và
   runtime state.
3. **Worker boundary:** worker API, Docker lifecycle, heartbeat và provider
   evidence.
4. **Service catalog:** YAML contract cho image, credentials, volumes,
   capabilities và collectors.
5. **Provider runtime:** automation đặc thù và collectors.
6. **Proxy/egress:** inventory, probe, assignment, lease release và rotation.
7. **Tests/evidence:** contract, deployment mode, collector, wallet và
   regression tests.
8. **CI/release/deployment:** workflows, Dockerfiles, Compose và release gates.

## Guided tour

1. Đọc `README.md`, `docs/getting-started.md` và application entry point.
2. Theo API deploy vào orchestrator và worker API.
3. Đọc service catalog cùng validation tests.
4. Theo Docker lifecycle, volume/label/state và heartbeat evidence.
5. Theo proxy probe/lease/rotation và điều kiện release dead lease.
6. Đọc MYST modules: wallet inventory/lease, identity persistence và
   WireGuard/TUN.
7. Đọc CI/release workflows để hiểu tag và UI/worker images.
8. Dùng `docs/research/repo-github-understanding.md` và
   `docs/ACTIVE_CONTEXT.md` trước mọi thao tác live.

## Hotspots

- `app/orchestrator.py`: trung tâm deploy và shared behavior; blast radius lớn.
- `app/worker_api.py`: Docker boundary, heartbeat và provider evidence.
- `app/database.py`: schema, history và lease/runtime synchronization.
- `app/myst_runtime.py` và `app/myst_wallets.py`: identity, funded wallet lease
  và sensitive state.
- `services/`: catalog contract cho provider; không normalize hàng loạt.
- `.github/workflows/`: release gates và publication của UI/worker images.

## Verification snapshot

- Baseline `main` full suite: `1311 passed, 7 skipped`.
- Current release: `v1.1.1`; both fork GHCR image manifests were published and
  verified by Auto Release.
- Current catalog: 14 providers; all 14 provider YAML files match the protected
  baseline hash.
- Grass references remaining in source are limited to the explicit retired
  provider boundary, legacy secret masking compatibility, tests and historical
  research/changelog records.

## Quy tắc làm việc an toàn

Trước mutation, xác minh HEAD, worktree, release/CI và live target. Với shared
code, lập call/data-flow và impact map; thêm regression tests; dùng canary
riêng; chuẩn bị rollback giữ nguyên identity, volumes, credentials và leases.
Không bulk deploy, cleanup hoặc merge upstream chỉ vì version mới hơn.
