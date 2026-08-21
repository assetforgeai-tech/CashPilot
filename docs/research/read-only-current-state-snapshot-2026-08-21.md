# Read-only Current-State Snapshot

Ngày: 2026-08-21

Phạm vi: repo artifacts, docs, Git metadata và test inventory. Không truy cập VPS/browser/live API trong lượt này.

## Repository/Fleet baseline (historical snapshot)

- The pre-removal source snapshot was captured at `0374956a2f60a77890a78432fb7b533e480fa537`.
- The removal branch `codex/remove-grass-provider` was created from
  `7588739f56a5ad20546ec8c71b3065407e0275ff`. This snapshot records the
  pre-publication evidence boundary and does not assert current worktree or PR
  status.
- At the time of this historical snapshot, fork `origin/main` pointed at the
  approved `7588739` base used by that worktree. It is not current state.
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
- NKN Wallet: owner-only import/list inventory và tests tồn tại; NKN không nằm trong active provider catalog và repo chưa có lease/deploy/heartbeat runtime flow. Live inventory chưa được snapshot.
- Raw wallet/credential values: không thu thập và không lưu.

## Settings snapshot

- Settings được xem là source of truth cho runtime policy và credentials theo `docs/configuration.md`.
- Chỉ ghi nhận schema/contract; không đọc plaintext secrets hoặc sửa database.

## Confidence

- `VERIFIED_REPO`: Git, graph, test inventory và docs.
- `HISTORICAL_LIVE_EVIDENCE`: các dòng worker/proxy/retired-provider evidence
  trong historical task artifacts.
- `LIVE_REQUERY_REQUIRED`: MYST completion, NKN inventory, proxy mapping hiện tại, Settings credential state và fleet current state.
- `SOURCE_GAP`: NKN runtime completion không thể live-verify vì current source chưa có active provider/lease/worker integration.

## Current repository pointer (added 2026-08-22)

The current verified repository pointer is `main` at `082b947ebdae31e9e0ced9eef76d5e53c9f16da6`, matching `origin/main` before the documentation-only audit branch. The fork release is `v1.1.1`; the fork is ahead 331 and behind 26 commits relative to `GeiserX/CashPilot`. These facts come from local Git and `gh`, not from a VPS.

This document remains a read-only historical evidence artifact. The source
snapshot and historical live lines above must not be treated as current live
state or as authorization to mutate a VPS. Current live status for MYST, NKN
inventory, Proxy Pool, Settings and Fleet remains unverified until a separately
approved read-only live snapshot is taken. Such a snapshot cannot establish an
NKN runtime contract that is absent from current source.
