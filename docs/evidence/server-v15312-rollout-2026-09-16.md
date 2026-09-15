# Server v1.53.12 rollout (2026-09-16)

Scope: CashPilot server only. Provider containers were not redeployed.

## Before

- `cashpilot-ui`: `ghcr.io/assetforgeai-tech/cashpilot:1.53.11`
- `cashpilot-worker`: `ghcr.io/assetforgeai-tech/cashpilot-worker:1.53.11`
- Existing UI and worker volumes were preserved.

## Action

The existing Compose project was run with a temporary override pinning both services to `1.53.12`:

```yaml
services:
  cashpilot-ui:
    image: ghcr.io/assetforgeai-tech/cashpilot:1.53.12
  cashpilot-worker:
    image: ghcr.io/assetforgeai-tech/cashpilot-worker:1.53.12
```

Commands used:

```text
docker compose -f docker-compose.yml -f docker-compose.v1.53.12.override.yml pull cashpilot-ui cashpilot-worker
docker compose -f docker-compose.yml -f docker-compose.v1.53.12.override.yml up -d --no-deps cashpilot-ui cashpilot-worker
```

## After

- Both containers run `1.53.12` and report Docker health `healthy`.
- Worker `/api/health` returned `{"status":"ok","worker":"local"}`.
- UI and worker retained their original `/data` and `/fleet` volumes.
- Existing provider containers remained running; no provider identity was recreated.
- Server DB still reports enrolled Azure workers `118903` and `118904` online at the rollout checkpoint.

## Remaining verification

Azure worker image rollout and provider dashboard traffic/earnings evidence remain separate gates. This operation proves only the server-side release transition and volume preservation.
