# Production-readiness status - 2026-09-12

## Verified

- Release `v1.33.1` is deployed to `cashpilot-ui` and healthy.
- Worker `43406` runs `ghcr.io/assetforgeai-tech/cashpilot-worker:1.33.3`; heartbeat is healthy and inventory is confirmed.
- Worker `92161` runs `ghcr.io/assetforgeai-tech/cashpilot-worker:1.33.3`; its heartbeat recovered after correcting the host boot fallback from the container-only `cashpilot-ui:8080` URL to the server URL.
- Worker `43406` reconciliation: 13 current reported containers match 13 persisted runtime rows; missing/untracked `0`.
- SQLite integrity and foreign-key checks passed in the post-release audit.
- Full local regression: `2840 passed, 8 skipped`.
- PR `#298` CI: Analyze, build, ruff, and test pass.

## Open gates

- Worker `90241` is a stale registration: read-only volume inspection found no matching active provider instances or leases; no deletion was performed without an explicit stale-worker policy decision.
- Token-expiry refresh/import, PayPal assignment/deletion, lease/release/sticky ownership mutation, and provider-wide heartbeat tests lack live evidence.
- Packet-capture evidence for IPv4/IPv6/DNS/DoH/UDP bypass and reboot persistence is incomplete.
- Full Azure auto-deploy, sequential provider/node execution, and one-hour recovery simulation remain unverified.

## Fresh verification (2026-09-12)

- Full repository suite: `2852 passed, 8 skipped`; Python `compileall` passed.
- Policy/runtime focused suite: `265 passed`.
- `test-sing` and `test-us` worker images are `1.33.3`, healthy, restart count `0`; server DB integrity is `ok`, foreign-key violations `0`.
- `test-us` server heartbeat is current and status `online`; its stale worker registration issue was isolated to the boot Compose fallback and fixed without touching EarnApp nodes.

## Safety boundary

Do not claim production-ready or run destructive recovery mutations until PR `#298` is approved, merged, deployed, and the open gates above have authoritative evidence.
