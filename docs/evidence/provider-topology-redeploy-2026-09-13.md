# Provider Topology Redeploy Evidence - 2026-09-13

## Release

- PR #319 merged at `95d15f28603da11830188b19ff8f4344e026b712`.
- Release `v1.44.0` published.
- Auto Release verified tests, lint, CodeQL, image build, and tag manifests.

## Runtime state

| Host | Component | Image | Health |
| --- | --- | --- | --- |
| CashPilot server | UI | `ghcr.io/assetforgeai-tech/cashpilot:1.44` | healthy |
| CashPilot server | worker | `ghcr.io/assetforgeai-tech/cashpilot-worker:1.44` | healthy |
| East Asia worker `20.187.79.110` | worker | `ghcr.io/assetforgeai-tech/cashpilot-worker:1.44` | healthy |
| Japan East worker `20.210.93.220` | worker | `ghcr.io/assetforgeai-tech/cashpilot-worker:1.44` | healthy |

Health endpoint returned `status=ok` on both Azure workers after redeploy. Existing provider containers were preserved; no provider mutation was performed during the version upgrade.

## Limitations

- Authenticated slot manifest and provider plan responses require owner authorization; no credential bypass was used.
- Direct-only, proxy-only, and hybrid live canary evidence remains pending.
- DNS/IPv6/UDP/DoH/DoT/direct-fallback probes remain pending per lane.
