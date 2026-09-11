# Traffmonetizer auth classification — 2026-09-11

- PR #259 merged as `1b9bb921297549f2521950483b0ec16d97bf83ef`.
- Release `v1.32.9` passed CI, image builds, tag verification, and publication.
- Live `cashpilot-ui` is healthy on `ghcr.io/assetforgeai-tech/cashpilot:1.32.9`.
- Live log now reports `Traffmonetizer credentials rejected - update the collector credentials` for HTTP `422`, instead of exposing a raw upstream error.
- Worker image/container/start time/restart count remained unchanged.
- SQLite integrity remains `ok`; foreign-key errors remain `0`.

The account credential itself is not changed automatically; an operator must update it.
