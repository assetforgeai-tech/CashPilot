# EarnApp production canary — 2026-09-08

## Scope

- Worker: `92161` on `vps-test-us`.
- Runtime: Docker-only macOS, iOS, Ubuntu.
- Two canary nodes per platform. Existing provider runtimes untouched.

## Runtime fix

The first macOS canary exited with code `1` because `boot.js` decrypted the
identity to `/run/mac-boot/identity.json`, while the CashPilot wrapper looked
for plaintext at `/etc/earnapp/identity.json`. The wrapper now reads the
decrypted tmpfs handoff. State volumes keep lifecycle markers only.

## Deployment evidence

| Platform | Nodes | Runtime image | CPU | Memory | Egress check |
| --- | --- | --- | ---: | ---: | --- |
| macOS | `macos-10`, `macos-11` | `asset-bd8de3ac58d1` | 1 core | 1 GiB | observed IP matched leased proxy |
| iOS | `ios-01`, `ios-02` | `asset-f384c554c3f8` | 1 core | 1 GiB | observed IP matched leased proxy |
| Ubuntu | `ubuntu-03`, `ubuntu-04` | `asset-89902b056dc4` | 1 core | 1 GiB | observed IP matched leased proxy |

All six containers were `running`, restart count `0` before reboot. UUIDs and
egress IPs were distinct per node. macOS logs showed tunnel establishment and
one-minute proxy heartbeats.

## Network checks

- `resolv.conf` points to `127.0.0.1`; CashPilot DoH sidecar is running.
- `CP_EARNAPP_OUT` ends in `DROP`.
- TCP/UDP DNS is redirected to the local resolver.
- TCP application traffic is redirected through the proxy route.

## Persistence

The worker was rebooted. After boot, all six canary containers returned to
`running` within the observed startup window, with the same state volumes and
node identities.

## Release

- PR: `#168`
- Release: `v1.21.24`
- Server UI and worker updated to `1.21.24` before the canary.

## Remaining proof

Positive EarnApp dashboard usage/country remains an external asynchronous
signal. Collector data must be checked at the next Earnings Update boundary;
container health alone is not treated as positive-usage proof.
