# Worker 1.40 live preflight — 2026-09-13

Both approved live-test workers are healthy:

| Worker | Image | Restart | Health | Provider inventory |
|---|---|---|---|---|
| East Asia (`20.187.79.110`) | `ghcr.io/assetforgeai-tech/cashpilot-worker:1.40` | `always` | HTTP 200 | empty |
| Japan East (`20.210.93.220`) | `ghcr.io/assetforgeai-tech/cashpilot-worker:1.40` | `always` | HTTP 200 | empty |

Observed on 2026-09-13 via SSH. Both systemd services report `active`. Both
retain the worker data volume and read-only public IPv4 slot volume. No provider
was deployed during preflight; this keeps canary mutation explicit and safe.
