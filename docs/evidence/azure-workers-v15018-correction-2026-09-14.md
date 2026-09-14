# Azure worker release correction

Date: 2026-09-14

## Scope

Only the two live-test Azure workers were touched. `test-sing` and `test-us`
were excluded. No provider node, proxy lease, account, scheduler, or provider
container was deleted, recreated, rotated, or released.

## Result

| Worker | Image | State | Restart policy |
| --- | --- | --- | --- |
| East Asia | `ghcr.io/assetforgeai-tech/cashpilot-worker:1.50.18` | `running|healthy` | `always` |
| Japan East | `ghcr.io/assetforgeai-tech/cashpilot-worker:1.50.18` | `running|healthy` | `always` |

The preflight detected both workers on `1.50.14`. Each was upgraded through
the existing `/CashPilot/docker-compose.worker.yml` project. The authoritative
worker-data volume, public-slot volume, worker identity/key fingerprints, and
provider container IDs were unchanged. The temporary compose-created empty
volume from the first failed project-name attempt was removed after confirming
it was not attached to the worker.

## Verification

- Full regression: `3069 passed, 10 skipped`.
- Both worker containers report `1.50.18`, healthy, and `restart=always`.
- Existing provider containers remain present on each worker.

## Remaining gates

This correction proves release deployment and persistence inputs only. Fresh
provider-dashboard earning evidence, proxy/DNS/IPv6/UDP leak matrix, and
authenticated UI sweep remain pending. No production-ready claim is made.
