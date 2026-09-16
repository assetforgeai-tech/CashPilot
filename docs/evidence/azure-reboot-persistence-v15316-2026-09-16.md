# Azure reboot persistence (2026-09-16)

The first reboot exposed a real operational defect: both worker systemd units
still referenced the stale `docker-compose.worker-v1.53.8.override.yml`.
Japan East consequently booted `cashpilot-worker:1.53.8` after reboot.

## Remediation

The unit on both scoped workers was updated to
`docker-compose.worker-v1.53.16.override.yml`, then daemon-reloaded and
restarted. The old unit was retained as a local rollback copy. No provider
container or data volume was deleted.

## Verification

Both workers were rebooted sequentially after the unit correction. Final
read-only checks showed:

- `ghcr.io/assetforgeai-tech/cashpilot-worker:1.53.16|running|healthy|0`.
- `285` managed provider containers running on each worker.
- Worker data, identity, and key hashes remained unchanged across each reboot.
- The provider-container inventory remained intact.
- `cashpilot-worker.service` now references the `v1.53.16` override on both
  workers.

This closes the worker-version reboot drift gate for the scoped Azure fleet.
