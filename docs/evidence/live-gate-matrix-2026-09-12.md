# CashPilot live-gate matrix — 2026-09-12

Status vocabulary: `verified` requires direct evidence; `unverified` means no
authoritative proof yet; `blocked` means the required observation path is
unavailable. No status below authorizes production deployment by itself.

| Gate | Status | Evidence | Next proof |
|---|---|---|---|
| Azure subscription/topology | verified | `azure-live-test-preflight-2026-09-11.md` | Recheck before each destructive scenario |
| East Asia bootstrap | verified | Worker enrollment and heartbeat evidence | Fresh bootstrap without recovery intervention |
| Japan East cloud-init | verified | Worker enrollment evidence | Fresh VM rebuild, then auto-deploy |
| Japan East reboot persistence | verified | Service active, worker healthy, 10 bridge networks, 10 slots after reboot | Route-rule and heartbeat log sample |
| Repository tests/lint/security | verified | `2821 passed, 8 skipped`; CodeQL/Ruff/build pass; pip-audit clean | Repeat after runtime fixes |
| Chrome profile 40 UI sweep | blocked | CDP unavailable in current session | Expose approved CDP session |
| Provider credentials/input | unverified | Inventory report only; secret values redacted | Authenticated provider inspection |
| Proxy metadata/location/IP type | unverified | API/UI implementation present | Live recheck sample across providers |
| UDP/DNS/IPv4/IPv6/DoH leak matrix | unverified | Unit coverage only | Packet capture per runtime/provider |
| EarnApp token auto-import/expiry | unverified | Source contracts/tests | Live extension/profile test |
| Lease/release/sticky ownership/rotation | unverified | Policy tests and DB schema | Live mutation matrix |
| Collector/payment/PayPal | unverified | API/UI source and tests | Authenticated provider collector test |
| One-hour shutdown/recovery | unverified | Reboot persistence only | Stop worker/VPS >1h, verify recovery |
| GHCR private image publication | unverified | No production image digest recorded | Publish with rotated credential, verify pull |
| Global auto-deploy | intentionally disabled | `cashpilot_auto_deploy_enabled=false` | Enable only after scoped live matrix passes |

## Decision

Infrastructure and repository gates pass. Production gate remains open until
the external-observation rows are directly verified. Legacy VPS cleanup is not
a prerequisite and remains out of scope.

## Read-only server snapshot (2026-09-12)

The CashPilot UI database was queried through the pinned server SSH helper,
without mutating state: 6 workers, 1,254 proxy endpoints (981 currently
`alive`), 4 EarnApp account rows, 85 EarnApp logical-node rows, and 20 active
provider proxy leases. These counts are reconciliation inputs, not proof that
all provider/runtime rows are healthy or that every lease is correctly routed.

## UI-only rollout (2026-09-12)

- Release `v1.33.0` deployed to `cashpilot-ui` only.
- UI is `healthy`; observed image digest: `sha256:23f17e1d2d472e72a6b8a4d940aabc8811109a3137e503ae6c441762a631aa7d`.
- Worker remained unchanged: healthy, restart count `0`.
- SQLite integrity: `ok`.
- `cashpilot_auto_deploy_enabled=false`; worker scope pinned to Azure workers
  `112494,112444`. No provider deployment was triggered.
- Pre-deploy database backup succeeded outside container `/tmp`.
