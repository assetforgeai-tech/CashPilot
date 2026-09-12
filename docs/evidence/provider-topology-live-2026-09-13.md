# Provider Topology Live Evidence

## Scope

Worker checked from `vps-test-us.txt` on 2026-09-13. Commands used the existing
worker container and Docker socket path; no container was created or removed.

## Observed runtime

- `cashpilot-worker`: healthy, `ghcr.io/assetforgeai-tech/cashpilot-worker:1.33.3`.
- iOS EarnApp node: running, bridge network, proxy egress probe returned `116.98.229.8`.
- macOS EarnApp node: running, bridge network, proxy egress probe returned `14.243.208.175`.
- The two nodes had distinct observed egress addresses; no paired egress was observed.

## Interpretation

This proves only that two active proxy lanes currently return different IPv4
egresses. It does not prove direct-only routing, DNS/IPv6/UDP leak absence, or
hybrid lane isolation. Those remain release gates until captured with a
confirmed worker inventory and expected lease egress values.
