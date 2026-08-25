# EarnApp legacy migration safety audit

Ngày kiểm tra: 2026-08-26  
Nhánh: `fix/earnapp-legacy-migration-safe`  
Base: `origin/main` / `4e336cb` (PR #41 đã merge)

## Phạm vi

Patch này chỉ gia cố migration SQLite của EarnApp Account Pool từ schema v18
sang v19. Không có thay đổi provider catalog, runtime, collector, worker,
proxy/wallet lease, identity, volume, Chrome profile live, VPS hoặc database
live. Không chỉnh compose pin trong patch này.

## Contract an toàn

1. Migration mở transaction `BEGIN IMMEDIATE`, bật deferred foreign keys và
   chỉ commit sau khi mọi bản sao, ràng buộc và `PRAGMA foreign_key_check` hợp
   lệ. Bất kỳ exception nào đều rollback.
2. Bảng v18 được đổi tên thành archive bất biến
   `earnapp_accounts_legacy_v18` và `earnapp_account_leases_legacy_v18`.
   Nguồn v19 bị bỏ dở được giữ ở `earnapp_accounts_v19_legacy`; không xóa bản
   duy nhất chứa credential.
3. Marker
   `migration.earnapp_accounts.legacy_v19=complete` chỉ có hiệu lực khi schema
   canonical và toàn bộ child contract còn nguyên: columns, types, defaults,
   PK, unique/index, FK/on-delete, archive tồn tại và không có duplicate ID.
4. Child table có FK về bảng cũ được rebuild có kiểm soát. Index/trigger nội bộ
   được lưu và khôi phục; trigger bên ngoài hoặc child table không được nhận
   diện sẽ làm migration dừng fail-closed thay vì âm thầm làm mất liên kết.
5. Legacy account không được tự chuyển `ACTIVE`. Legacy active lease trở thành
   logical node `RECOVERABLE` với ID deterministic; Chrome import rõ ràng mới
   được phép adopt account.
6. Khi đối chiếu interrupted v19 copy, credential Fernet được so bằng plaintext
   giải mã (không so ciphertext, vì mỗi lần encrypt tạo token khác nhau). Hai
   decrypt thất bại không được coi là bằng nhau.

## Bằng chứng kiểm thử

- Focused EarnApp/Chrome/proxy/UI: `369 passed`.
- Full non-live: `1854 passed, 8 skipped` sau khi fetch đúng fork-tag refspec
  mà CI sử dụng (`+refs/tags/*:refs/fork-tags/*`). Compose pin `1.11` khớp
  release series hiện tại và không bị sửa bởi hotfix.
- `ruff check .`: pass.
- `python -m compileall -q app tests`: pass.
- JavaScript `node --check`: pass.
- `python scripts/check_deploy_baseline.py`: pass.
- `git diff --check`: pass.
- `ruff format --check .`: chỉ báo file kế hoạch lịch sử không đổi
  `docs/superpowers/plans/2026-08-25-proxy-import-protocol.md`.

## Release/deploy boundary

- Chỉ tạo patch release `v1.11.2` sau khi PR review và CI của patch xanh.
- Nếu deploy được phê duyệt, backup database trước, triển khai đúng UI image
  digest duy nhất và chỉ recreate `cashpilot-ui`.
- Không redeploy/recreate `cashpilot-worker`, provider container, NKN/MYST,
  proxy sidecar, wallet/identity volume; không thao tác VPS live thủ công.
- Sau deploy chỉ thực hiện snapshot read-only: integrity/schema/marker/archive,
  account/lease/logical-node counts và provider invariants.
