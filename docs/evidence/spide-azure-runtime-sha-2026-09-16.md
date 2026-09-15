# Spide Azure runtime verification (2026-09-16)

Scope: the two authorized Azure workers only.

| Worker | Worker image | Spide runtime containers | Runtime SHA-256 |
|---|---|---:|---|
| `20.187.79.110` / `118903` | `ghcr.io/assetforgeai-tech/cashpilot-worker:1.53.12`, healthy | 20 (10 direct, 10 proxy) | `04f31522cbdb03b3d11e5293a3a18c6e910aed11b6d8b431b560bc7cb4ed08e5` on every sampled container |
| `20.210.93.220` / `118904` | `ghcr.io/assetforgeai-tech/cashpilot-worker:1.53.12`, healthy | 20 (10 direct, 10 proxy) | `04f31522cbdb03b3d11e5293a3a18c6e910aed11b6d8b431b560bc7cb4ed08e5` on every sampled container |

The container process is `/data/spide/spide_cli/spide`. The archive is the R2 artifact pinned by the catalog. No collector process or collector source is present in the runtime container.

This proves artifact provenance and runtime process selection. It does not prove provider dashboard earnings; that requires authenticated dashboard/API evidence.
