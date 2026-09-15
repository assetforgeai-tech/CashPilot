# Spide live runtime recheck (2026-09-16)

Read-only verification against the two production-test Azure workers.

| Worker | Host | Spide containers | Sample executable SHA-256 |
|---|---|---:|---|
| `118903` | `20.187.79.110` | 20 (10 runtime + 10 egress) | `04f31522cbdb03b3d11e5293a3a18c6e910aed11b6d8b431b560bc7cb4ed08e5` |
| `118904` | `20.210.93.220` | 20 (10 runtime + 10 egress) | `04f31522cbdb03b3d11e5293a3a18c6e910aed11b6d8b431b560bc7cb4ed08e5` |

Both sampled runtimes were up for approximately nine hours. The executable
hash matches the catalog pin and the authoritative R2 artifact. No container
was recreated or mutated during this check.

The server UI and worker images remain `1.53.12` and healthy. This check proves
runtime artifact parity and process continuity; it does not prove per-device
dashboard earnings or map a local container to a provider device.
