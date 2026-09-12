# Release v1.33.2 rollout - 2026-09-12

- GitHub Auto Release run `34676635227` completed successfully.
- Release `v1.33.2` is published from merge commit `1e4a2da4301e3bad54cdb50b79f5a14134f356d3`.
- Server `cashpilot-ui` was recreated only and is healthy on `ghcr.io/assetforgeai-tech/cashpilot:1.33.2`; restart count is `0`.
- Server-local `cashpilot-worker` remained on custom image `cashpilot-worker-local:proxy-egress`; it was not recreated.
- Worker `43406` was upgraded to `ghcr.io/assetforgeai-tech/cashpilot-worker:1.33.2`; it is healthy and heartbeat returned HTTP `200`.
- Server-local worker was then migrated from `cashpilot-worker-local:proxy-egress` to `ghcr.io/assetforgeai-tech/cashpilot-worker:1.33.2` after confirming the managed `proxy_egress.py` implementation matched. Worker ID persisted, health became `healthy`, and heartbeat returned HTTP `200`.
- Server-local Wipter and its egress sidecar retained their container IDs and running state during worker migration.
- EarnApp containers on worker `43406` remained present; rollout did not delete, recreate, unlink, release, or rotate an EarnApp node.
- Server SQLite checks: `integrity_check=ok`; `foreign_key_check` returned `0` rows.
- Follow-up release `v1.33.3` was published from merge commit `8c505e23198df1e89bfb163d0b1fd2f5135eb484`; GHCR tag verification passed.
- Server UI and server-local worker now run `v1.33.3`, both healthy; worker heartbeat returned HTTP `200`.
- Server-local Wipter and its egress sidecar remained running with unchanged container IDs during the worker upgrade.
- Post-`v1.33.3` SQLite checks: `integrity_check=ok`; `foreign_key_check` returned `0` rows.
- Worker logs after rollout contained heartbeat success and no `proxy/finalize` or reconciliation error loop.
- Post-release local gates: full suite `2849 passed, 8 skipped`; `pip-audit` reported no known vulnerabilities; Bandit reported `0 HIGH` findings.
- Worker `90241` remains offline with an internal URL and no matching credential file in the workspace; no mutation was attempted.

## Scope note

The server-local worker was initially a custom local image. It was migrated only after comparing the proxy-egress implementation and preserving `/data`; generic replacement before that check would have been unsafe.
