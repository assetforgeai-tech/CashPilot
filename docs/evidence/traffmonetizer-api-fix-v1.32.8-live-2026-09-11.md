# Traffmonetizer collector fix — 2026-09-11

## Root cause

The live Traffmonetizer dashboard bundle declares `https://data.traffmonetizer.com` as its API origin. CashPilot used `https://app.traffmonetizer.com/monetizer_api/api`; that endpoint returned HTTP `405`.

## Fix and verification

- PR #257 merged as `ffc1e4c427c20ac520b0fc0eb6fae7c94e7c7f66`.
- Release `v1.32.8` completed CI, builds, image verification, and publication.
- Live `cashpilot-ui`: `ghcr.io/assetforgeai-tech/cashpilot:1.32.8`, healthy, restart count `0`.
- Live collector reports `https://data.traffmonetizer.com/api`.
- Live SQLite integrity: `ok`; foreign-key errors: `0`.
- `cashpilot-worker` remained unchanged: image `cashpilot-worker:1.32.0`, original container ID/start time, restart count `0`.

An invalid-credential request to the new API returns `422`, confirming the route exists; no real credential was used or logged.
