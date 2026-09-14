# Azure worker 1.51.13 rollout

Captured 2026-09-15 on the two production live-test workers only.

| Worker | Image | State | Health | Restart count | Provider containers preserved |
|---|---|---|---|---:|---|
| 118903 (`20.187.79.110`) | `ghcr.io/assetforgeai-tech/cashpilot-worker:1.51.13` | running | healthy | 0 | yes |
| 118904 (`20.210.93.220`) | `ghcr.io/assetforgeai-tech/cashpilot-worker:1.51.13` | running | healthy | 0 | yes |

The rollout preserved worker data volume, public-IP slot volume, worker identity hashes,
and existing provider container IDs. The worker compose file was used; the worker
heartbeat endpoint remains the server URL `http://42.96.13.215:8080`.

Spide remained at 20 service containers per worker. Runtime probes ended with
`Status: OK` for all checked service containers after the rollout.
