# Read-only Current-State Snapshot

Ngày: 2026-08-21

Phạm vi: repo artifacts, docs, Git metadata và test inventory. Không truy cập VPS/browser/live API trong lượt này.

## Repository/Fleet baseline

- The pre-removal source snapshot was captured at `0374956a2f60a77890a78432fb7b533e480fa537`.
- The removal branch `codex/remove-grass-provider` was created from
  `7588739f56a5ad20546ec8c71b3065407e0275ff`. This snapshot records the
  pre-publication evidence boundary and does not assert current worktree or PR
  status.
- Fork `origin/main` points at the approved `7588739` base used by this worktree.
- Worker evidence đã ghi trong `docs/ACTIVE_CONTEXT.md`: worker id `34253`, version `1.0.10`, heartbeat `2026-08-20 17:08:47`.
- Đây là historical evidence từ ACTIVE_CONTEXT, không phải live re-query mới.

## Proxy Pool snapshot

- Historical evidence: active lease `proxy_id=2`, provider `vtproxy`, endpoint `dc-t5.proxyvt.com:41231`, fallback `hold`.
- Historical Grass node-1 egress evidence is retained for audit only; Grass is
  no longer part of the current product catalog.
- Không rotate lease; không xác nhận lại live trong lượt này.

## Wallet snapshot

- MYST Wallet: inventory/lease/runtime contracts có source và tests; funded lease và traffic completion chưa có live snapshot mới.
- MYST current contract là direct-only. Stale historical client IDs như `mysterium-proxy` không chứng minh proxy mode còn được hỗ trợ và không được dùng làm deployment guidance.
- NKN Wallet: module và tests tồn tại; inventory/funding/runtime live state chưa được snapshot.
- Raw wallet/credential values: không thu thập và không lưu.

## Settings snapshot

- Settings được xem là source of truth cho runtime policy và credentials theo `docs/configuration.md`.
- Chỉ ghi nhận schema/contract; không đọc plaintext secrets hoặc sửa database.

## Confidence

- `VERIFIED_REPO`: Git, graph, test inventory và docs.
- `HISTORICAL_LIVE_EVIDENCE`: các dòng worker/proxy/retired-provider evidence
  trong historical task artifacts.
- `LIVE_REQUERY_REQUIRED`: MYST completion, NKN runtime, proxy mapping hiện tại và fleet current state.

This document remains a read-only evidence artifact. The source snapshot and
historical live lines above must not be treated as current live state or as
authorization to mutate a VPS.
