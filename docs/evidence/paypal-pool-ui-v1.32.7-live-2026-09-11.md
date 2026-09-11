# PayPal Pool UI live verification — 2026-09-11

## Scope

UI-only release. No worker or provider containers were redeployed.

## Evidence

- PR #254 merged as commit `1284e2e8c57272e135d7d50eaff0a9a69e77a914`.
- Release `v1.32.7` completed CI, lint, tests, image builds, tag verification, and publication.
- Live `cashpilot-ui`: `ghcr.io/assetforgeai-tech/cashpilot:1.32.7`, running, healthy, restart count `0`.
- Live template contains exactly one `earnapp-paypal-destination` input.
- Live PayPal API without auth returns HTTP `401`, confirming the protected route is present.
- Live SQLite `integrity_check`: `ok`.
- Live SQLite foreign-key errors: `0`.
- `cashpilot-worker` remained unchanged: image `ghcr.io/assetforgeai-tech/cashpilot-worker:1.32.0`, healthy, restart count `0`, original start time preserved.

## Remaining limitation

This verifies CashPilot UI presence and route protection. It does not claim external EarnApp PayPal configuration success; upstream `redeem_details` has returned intermittent `404`/`406`, so the payment path remains fail-closed until a read-back confirmation is received.
