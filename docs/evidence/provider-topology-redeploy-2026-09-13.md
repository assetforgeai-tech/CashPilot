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

## Contract hardening follow-up

- Duplicate public IPv4 records are discarded before slot cardinality is calculated.
- Hybrid providers expose `N direct + N proxy` as the desired formula; proxy shortage only blocks deployment.
- Hybrid lifecycle dispatch requires an explicit lane; ambiguous provider-level signals observe only.
- Catalog/topology responses expose slot binding, health signal sources, and concrete proxy UDP/DoH/DoT defaults.
- PR #320 merged; PR #321 carries the follow-up contract changes and is awaiting CI.

## Read-only runtime preflight

- Server UI and worker containers report `healthy` on `1.44`.
- East Asia worker reports one preserved direct provider container with `restart=always` and a dedicated `cashpilot-direct-ipv4-001` bridge.
- Japan East worker reports a healthy worker and no provider mutation was performed.
- The server's Wipter runtime uses a dedicated egress container namespace and `restart=always`.
- Worker-local Docker DNS/route inspection was collected without exposing credentials.

These observations prove service/runtime availability only; they do not replace owner-authorized provider plans or lane-specific egress probes.
