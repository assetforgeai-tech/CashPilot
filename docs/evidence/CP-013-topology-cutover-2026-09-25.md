# CP-013 topology cutover — 2026-09-25

## Scope

- Canonical control-plane: `42.96.13.215:8080`.
- Production worker: Azure VM `cashpilot-prod-ea`.
- Azure subscription: `a9d21cd7-abf8-4b14-a2e5-1867178fd5f6`.
- Azure resource group: `RG-CASHPILOT-PRODUCTION-EASTASIA-20260924`.
- No provider, proxy, wallet, lease, account-pool, or provider-node mutation.

## Completed

- Added NSG rule `cashpilot-canonical-control-8081`: TCP `8081`, source
  `42.96.13.215/32` only. No public-wide worker API rule added.
- Preserved worker identity `.worker_id`; re-enrolled the worker with the
  canonical fleet key and confirmed its per-worker key.
- Worker registration: ID `172243`, client ID
  `65abae8aea7c4d1295cddb7ca62ecfb8`, status `online`, URL
  `http://20.24.193.21:8081`, enrollment `confirmed`.
- Canonical control-plane command path verified with worker `/healthz`,
  `/api/status`, and `/api/network/slots`.
- All 20 Azure public-IP slots reported `route_ready=true` through the worker
  API.
- Updated `cashpilot_autodeploy_worker_ids` to `172243`.
- Temporarily set `cashpilot_auto_deploy_enabled=false` during cutover. This
  prevents the three-heartbeat auto-deploy trigger from mutating provider state
  before the release/version gate is resolved.
- Isolated the Azure-local `cashpilot-ui`: stopped only that container and set
  its Docker restart policy to `no`. Its DB/data volume was retained; an
  integrity-checked DB snapshot was created under `/opt/cashpilot/backups/`.
- `cashpilot-worker` remained running and healthy after local UI isolation.

## Verification

- Canonical API returned HTTP 200.
- Worker heartbeat remained online after the local UI stopped.
- Canonical UI successfully reached the worker command API.
- Worker ID remained unchanged across reconfiguration/recreate.
- No raw key, token, password, cookie, or private key is present in this
  evidence.

## Blocker

At cutover, the canonical control-plane reported UI version `1.66.0` while the
Azure worker reported `1.68.3`; `version_skew=true`. The UI upgrade gate below
resolved this particular skew. Provider deployment remains disabled until a
separately authorized stage.

## Next gate

1. Upgrade/verify canonical UI release without changing DB, keys, workers,
   provider state, wallets, leases, or account pools.
2. Re-run worker health, command, heartbeat, version-skew, and rollback checks.
3. Only then enable auto-deploy for worker `172243` and deploy provider groups
   with per-group dashboard/egress/DNS/heartbeat/lease evidence.

## UI upgrade gate - 2026-09-25

Approved scope: backup canonical control-plane and recreate only `cashpilot-ui`
with immutable v1.68.3 image. No worker, provider, node, proxy, lease, wallet,
account-pool, Azure, or auto-deploy mutation was authorized or performed.

### Backup

- Host: `42.96.13.215:26266`.
- Backup: `/opt/cashpilot/backups/ui-upgrade-20260925T052430Z`.
- Included `docker-compose.yml`, live SQLite backup, secret-free manifest and
  checksums. The host has no `/opt/cashpilot/.env`; none was created.
- Backup DB integrity: `ok`; size: `271966208` bytes; tables: `37`.
- Backup checksum verification: pass.

### Change and verification

- Previous UI image:
  `ghcr.io/assetforgeai-tech/cashpilot@sha256:2bcc9766d41cc8345547277b8f8e07a721e43760749d634691c66d4654536575`.
- Deployed UI image:
  `ghcr.io/assetforgeai-tech/cashpilot@sha256:8931d1318ae443b70f844dd9d7513018c795281bee78add4fee77f9367449ed9`.
- Exact digest pulled and verified before `docker compose up -d --no-deps
  cashpilot-ui`. UI restart policy remains `unless-stopped`.
- `cashpilot-worker` image/start time unchanged and health `healthy`.
- UI root HTTP `200`, page reports `v1.68.3`; UI `/api/status` HTTP `200`.
- Worker `172243` (`cashpilot-prod-ea`): online, key confirmed, heartbeat
  fresh, v1.68.3, UI/worker `version_skew=false`.
- Worker public-IP slots: `20`; route-ready: `20`.
- Fleet summary readable: `2` online workers, `7` active registrations,
  `1` running service.
- `cashpilot_auto_deploy_enabled=false` and
  `cashpilot_autodeploy_worker_ids=172243`.
- DB integrity after verification: `ok`. Critical row counts for workers,
  provider instances, proxy endpoints/leases, NKN/Myst wallets and EarnApp
  accounts unchanged. Dynamic telemetry tables (`earnapp_account_snapshots`,
  `health_events`, `worker_resource_reclamations`) advanced during operation.
- A command-path probe targeting a nonexistent slug returned `Worker request
  failed` through the canonical UI. A subsequent read-only diagnostic using
  the canonical UI runtime `_proxy_to_worker` returned HTTP `200` for both
  worker `/api/status` and `/api/network/slots`: client ID matched the enrolled
  worker, Docker was available, and all 20 slots reported `route_ready=true`.
  No provider container was changed.

UI upgrade gate: **PASS**. Auto-deploy remains disabled; no production-ready
claim. Follow-on private/TLS transport and staged provider-group deployment
require separate scope/approval. No secret is included in this evidence.
