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

## EarnApp runtime image publication (2026-09-12)

- Published private GHCR candidate tag `20260912-production-candidate` for
  MacOS, iOS, and Ubuntu runtime images.
- Digests: MacOS `sha256:45c62c73242a281f5e293a6249bae4706b3c2ff8f9ec23a01b3a01a7a879170d`; iOS `sha256:f7ca70ce9ef7bd72321bafa8be3f00047ceb056e67221ac93c10394592049930`; Ubuntu `sha256:70265ba720c27bb9398f97432fd9e151f841aedf679c1f82831080ac9d0109e3`.
- Build/push completed through the existing controlled script; temporary token
  and staging files were removed. Secret values are absent from the publish log.
- The server-side GHCR session was logged out and the staging token/script files
  were removed. GHCR package API visibility could not be queried from this
  workstation because its token lacks `read:packages`; package privacy remains
  `unverified` until an authenticated read-only query is run.

## Read-only credential/worker snapshot (2026-09-12)

- EarnApp accounts: 2 `ACTIVE`, 2 `DELETED`.
- Rows with persisted `token_expires_at`: `0`; rows marked
  `needs_token_refresh`: `0`. This is missing expiry evidence, not proof that
  upstream tokens cannot expire.
- Workers: 5 `online` of 6 total.
