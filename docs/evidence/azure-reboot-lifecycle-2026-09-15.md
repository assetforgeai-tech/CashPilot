# Azure reboot lifecycle evidence

Captured 2026-09-15 on the two authorized Azure workers only.

## Worker 118903

- Reboot completed.
- `cashpilot-worker.service`: active (exited).
- Worker image: `ghcr.io/assetforgeai-tech/cashpilot-worker:1.52.6`.
- Worker container: running and healthy.
- `cashpilot-nkn-agent.service`: active.
- NKN LXD containers: 10; count preserved.
- `/data` identity and provider IDs preserved by guarded upgrade check.

## Worker 118904

- Reboot completed.
- `cashpilot-worker.service`: active.
- Worker image: `ghcr.io/assetforgeai-tech/cashpilot-worker:1.52.6`.
- Worker container: running and healthy.
- `cashpilot-nkn-agent.service`: active.
- NKN LXD containers: 4; count preserved.

## Defect fixed during gate

The previous systemd unit pinned `1.50.18`, causing a reboot rollback. It was
replaced with a pinned `1.52.6` unit using the same Compose project and a
worker-only stop action. A second reboot verification passed on both workers.

NKN stale containers remain unadopted because server authority has reclaimed
their leases; no wallet or container was deleted.
