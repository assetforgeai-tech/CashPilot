# EarnApp production canary — 2026-09-08

## 2026-09-09 macOS non-VN canary

- `earnapp-canary-us-macos-nonvn-01`: `ACTIVE`, worker `92161`, device `sdk-mac-70b1989773eca3d6157bec6e6df80b96`, proxy `130.180.234.47` (`US`, residential), container running.
- `earnapp-canary-us-macos-nonvn-02`: `ACTIVE`, worker `92161`, device `sdk-mac-491639397177d293f957e44291bab9bb`, proxy `62.164.242.0` (`US`, residential), container running.
- Both proxies passed latest `earnapp_wss` qualification (`CID_SET`, `eligible`); egress IPs are unique.
- Existing VN macOS nodes were not modified. Earnings/usage remains pending the normal EarnApp update cycle.

## 2026-09-09 six-node gate

- macOS: `earnapp-canary-us-macos-nonvn-01` and `-02` are `ACTIVE`, Docker `running`, with unique US residential egress.
- iOS: `earnapp-canary-us-fresh-ios-01` and `earnapp-canary-us-production-ios-02` are `ACTIVE`, Docker `running`, with unique VN residential proxies.
- Ubuntu: `earnapp-canary-us-fresh-ubuntu-01` and `-02` are `ACTIVE`, Docker `running`, with unique US residential egress.
- All six have exclusive leases, healthy proxy state, and worker heartbeat `92161` online. Collector calls for accounts `2` and `470` returned HTTP 200.
- Snapshot `2026-09-08 17:43:59-17:44:04` reports Ubuntu country/usage; new macOS/iOS devices still await country/usage propagation. Clean-reboot and positive-usage verification remain open.
- Clean reboot completed on `vps-test-us` at `2026-09-08 17:48:20Z`; SSH returned and worker `92161` reported `online` at `17:49:04Z`. All six canary containers returned `running`; all six logical nodes remained `ACTIVE` with the same proxy IDs and worker assignment.
- Release `v1.23.2` was deployed to the CashPilot server on `2026-09-08`; UI and worker containers are healthy. The two macOS non-VN nodes were restarted through the CAS-aware Docker lifecycle route. Their logical state, generation, device IDs, proxy IDs, and worker assignment remained unchanged; both containers remained running with increasing network counters.
- Post-deploy collector checks for accounts `2` and `470` returned HTTP 200. Account-level totals remain healthy, but per-device macOS usage still requires the next EarnApp earnings boundary before it can be marked positive.
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

The reboot audit also found that the live worker container was operator-created
and had no Compose project labels, while the systemd unit attempted `docker
compose up`. That produced a container-name conflict despite the worker being
healthy. The unit now starts the existing `cashpilot-worker` container first
and falls back to the pinned `1.21.24` Compose definition only when it is absent.
The unit is enabled/active with `Result=success`; all six EarnApp container IDs
and uptimes were unchanged by this repair.

## Release

- PR: `#168`
- Release: `v1.21.24`
- Server UI and worker updated to `1.21.24` before the canary.

## 2026-09-08 follow-up

- Boundary recovery fix merged as PR `#175`, released as `v1.21.27`, and
  deployed UI-only. The worker image/container and all six EarnApp nodes were
  unchanged.
- Runtime fidelity gate merged as PR `#176`, released as `v1.21.28`, and
  deployed UI-only. Context staging now verifies the three reference image
  pins, artifact hashes, proxy/DoH entrypoint wiring, and complete artifact
  sets before any EarnApp image build.
- Post-deploy server evidence: UI `v1.21.28` healthy, worker remained
  `1.21.24`, worker restart count `0`; no node recreation or proxy lease change.

## Remaining proof

Positive EarnApp dashboard usage/country remains an external asynchronous
signal. Collector data must be checked at the next Earnings Update boundary;
container health alone is not treated as positive-usage proof.

## v1.22.8 lifecycle recovery verification

- PR `#187` anchored a first observed positive Earnings Update countdown to a
  durable cycle ID. PR `#188` preserved that account-level cycle even when the
  EarnApp device-status payload temporarily omitted a device.
- Focused lifecycle, policy-matrix, and collector tests passed: `90 passed`.
- Server UI and `vps-test-us` worker were deployed at `v1.22.8`; both reported
  healthy with restart count `0`. The worker firewall remained active.
- The first post-upgrade scheduler pass restarted iOS-01 once and atomically
  persisted matching `earnings_cycle_id` and `last_recovery_cycle_id`.
- The following five-minute pass did not restart any of the six live canaries.
  Existing `409` calls target legacy ACTIVE database rows whose containers are
  absent; they are separate cleanup work and did not mutate the six canaries.
- The restart preserved the iOS-01 device UUID, proxy assignment, named volume,
  account assignment, and container identity. No remote delete, link, lease
  release, or proxy rotation occurred.
- A fresh authenticated collector run succeeded for accounts `2` and `470`.
  Both macOS canaries were online with VN country and their expected distinct
  proxy IPs; Ubuntu-01 was online with US country. iOS-02 and Ubuntu-02 were
  online but still awaiting country/usage propagation. Positive usage for all
  six remains a production-closeout gate.
