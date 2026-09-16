# Server UI v1.53.15 rollout (2026-09-16)

The CashPilot server UI was upgraded to
`ghcr.io/assetforgeai-tech/cashpilot:1.53.15` with a UI-only Compose override.
The server worker was not recreated. `/data` and `/fleet` mounts were
preserved, and SQLite `PRAGMA integrity_check` returned `ok`.

Post-rollout authority snapshot:

- Workers `118903` and `118904`: `online`, `1.53.15`, current heartbeats.
- Both workers: `183/183` containers running.
- UI and worker `reference_version`: `1.53.15`.
- Provider rows remained running; no provider container mutation was requested.

Known remaining collector signals are unchanged: Repocket is disconnected,
and Traffmonetizer is rate-limited. This rollout does not claim those gates
are resolved.
