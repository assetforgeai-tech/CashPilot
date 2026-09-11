# Live reconciliation — 2026-09-11

Read-only authenticated API snapshot from the CashPilot server. No provider,
proxy, account, or worker mutation was performed.

## Server

- `cashpilot-ui` `v1.32.16`: `running|healthy`, restart count `0`.
- `cashpilot-worker`: healthy, restart count `0`; DB integrity `ok`, foreign
  keys `0`; `50` provider instances and `21` active proxy leases.
- PayPal Pool: `1` masked destination.

## Worker reconciliation

- Worker `92161`: inventory confirmed; EarnApp DB/runtime sets match; 3/3 nodes
  reported online; network reconciliation `pass`.
- Worker `43406` (`test-sing-nkn-canary`): heartbeat online, but inventory is
  `unverified`; 18 EarnApp instances are reported, while provider state totals
  classify only 17 (`7` online, `10` offline). Several rows have
  stale/unhealthy proxy observations, so this worker is not production
  evidence. NKN runtime is reported exited.
- Worker `3113`: Wipter inventory confirmed and network reconciliation `pass`.
- Worker `90241`: stale/offline heartbeat; no current live evidence.

## Decision

The server control plane is healthy, but fleet-wide production readiness remains
open until the test-sing worker inventory/storage issue and provider-wide live
network/reboot evidence are resolved. Unknown or stale telemetry remains
`unverified`, never `pass`.
