# Provider Topology Live Evidence

## Scope

Worker checked from `vps-test-us.txt` on 2026-09-13. Commands used the existing
worker container and Docker socket path; no container was created or removed.

## Observed runtime

- `cashpilot-worker`: healthy, `ghcr.io/assetforgeai-tech/cashpilot-worker:1.33.3`.
- This worker is older than the released `v1.40.0`; the observation is therefore
  useful for network shape only, not proof of the current production worker.
- iOS EarnApp node: running, bridge network, proxy egress probe returned `116.98.229.8`.
- macOS EarnApp node: running, bridge network, proxy egress probe returned `14.243.208.175`.
- The two nodes had distinct observed egress addresses; no paired egress was observed.
- Both containers reported `nameserver 127.0.0.1`.
- Both containers had `CP_EARNAPP_OUT` with loopback/established-state allow rules,
  one provider endpoint allow rule, then terminal `DROP`.
- Both had `redsocks`, the EarnApp process, and the CashPilot DoH helper running.
- IPv6 probe failed to connect; this is a negative observation, not a complete
  IPv6 leak proof.
- Follow-up inspection confirmed both containers have explicit `CP_EARNAPP6_OUT`
  chains that allow loopback only, then drop non-loopback IPv6 output. This is
  enforcement evidence, not a complete application-level IPv6 proof.
- Both containers expose loopback DNS at `127.0.0.1:1053`; redsocks is running.
- Egress remained distinct: iOS `116.98.229.8`, macOS `14.243.208.175`.
- No mutation, restart, lease change, or container change occurred.

## Interpretation

This proves two active proxy lanes return different IPv4 egresses and have the
expected in-container fail-closed shape. It does not prove direct-only routing,
complete DNS/IPv6/UDP leak absence, or hybrid lane isolation. Those remain
release gates until captured with a confirmed worker inventory and expected
lease egress values.

## Additional preflight

- SSH user `kalinh` cannot access `/var/run/docker.sock`; read-only commands required `sudo`.
- VPS has one private `eth0` address (`10.0.0.4`) and Docker bridge networks only; no public IPv4 slot inventory was exposed by `ip -4 addr`.
- Host `OUTPUT` policy is `ACCEPT`; this is not sufficient evidence for container lane isolation.
- Docker server version: `29.1.3`.
- Current worker image remains `1.33.3`, older than the released `v1.40.0`.

These facts block direct-only and hybrid production claims on this VPS. They do
not justify changing host firewall or Docker permissions during a read-only audit.
