# Release v1.33.3 rollout - 2026-09-12

- PR `#299` merged as `8c505e23198df1e89bfb163d0b1fd2f5135eb484` after CI passed.
- Auto Release run `34681447906` completed successfully; UI/worker GHCR tags and image version metadata verified.
- Server `cashpilot-ui` and server-local `cashpilot-worker` run `v1.33.3`, both healthy.
- Server worker heartbeat returned HTTP `200`; SQLite `integrity_check=ok` and `foreign_key_check` returned `0` rows.
- Wipter and its managed egress sidecar retained their running state and container IDs during worker upgrade.
- EarnApp node containers were not mutated by the rollout.
- Shared lifecycle policy now reports EarnApp node `banned => restart`; node identity, proxy, and generation remain preserved.

## Fresh worker recheck (2026-09-12)

- `test-sing` worker `43406`: `ghcr.io/assetforgeai-tech/cashpilot-worker:1.33.3`,
  healthy, restart count `0`; policy catalog reports EarnApp `banned=restart`.
- `test-us` worker `92161`: upgraded from stale `drumsergio/cashpilot-worker:1.33`
  to `ghcr.io/assetforgeai-tech/cashpilot-worker:1.33.3`; image ID
  `sha256:8102c296d75d7f291f00111138e9f00442e1565a414eef9fe634b388c7c59a3b`,
  healthy, restart count `0`; worker identity, volumes, and non-worker containers
  were unchanged.
- `test-us` was offline because its Compose environment used the container-only
  URL `http://cashpilot-ui:8080` while the worker runs outside the UI network.
  The boot Compose fallback now uses the primary `docker-compose.yml`, the worker
  uses the server URL, and a fresh heartbeat returned HTTP 200.
- Server reconciliation after the fix: workers `3113`, `43406`, `92161`,
  `112444`, and `112494` online; `90241` remains offline and unresolved.
  SQLite integrity `ok`; foreign-key violations `0`.
- No EarnApp node, proxy lease, account, scheduler, or provider container was
  mutated during this recheck.

## Remaining gates

- Worker `90241` remains offline and has no approved live credential path.
- Provider-wide live packet-capture, Azure recovery, private-GHCR pull, Wipter migration canary, and authenticated Chrome UI sweep remain unverified.
