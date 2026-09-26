# CP-013 NKN recovery gate — 2026-09-26

## Scope and approval

- Target only: subscription `a9d21cd7-abf8-4b14-a2e5-1867178fd5f6`, RG `RG-CASHPILOT-PRODUCTION-EASTASIA-20260924`, VM `cashpilot-prod-ea`, worker `172243`.
- Approved mutation: update `cashpilot-nkn-agent.service` to the `v1.68.8` unit contract, set `RuntimeDirectoryPreserve=yes`, reload systemd, restart the helper, then restart the existing `cashpilot-worker` container exactly once to refresh the bind mount.
- Explicitly not performed: NKN deploy/retry, provider command, provider-node recreation, wallet/proxy/lease/account-pool mutation, DB/data/fleet-volume mutation, worker recreation, image/compose change, Azure-resource mutation, or auto-deploy enablement.

## Pre-change baseline

- Existing unit SHA-256: `01784de0adfd1443fc2d2b64db77f10c39524196188bbf87692306007abc0ca8`
- Existing compose SHA-256: `1374186813193d73bcaa419ce96e8dc1778e2466103a6dc26e5e2b4b5597cca9`
- Existing unit setting: `RuntimeDirectoryPreserve=no`
- Existing worker container ID: `2aacbc255a3e331bf63fd835520a836e3be55d13ca1a1aa7f73df538c9abc47a`
- Existing worker image digest: `sha256:1b5468144c3c4e457279c8d6c9ec2a6fbef46c1759b32836607d15c1c4986005`
- Initial host runtime-directory device/inode: `28:140377`

## Recovery transaction

- Backup directory: `/data/cp013-nkn-recovery-20260926T034626Z`
- Applied unit SHA-256: `9ce6fccc3552130ba3ed810f7d4a3bfad8b4be5b9969503fb8a5e0aaaccd969a`
- `RuntimeDirectoryPreserve=yes` applied.
- `systemctl daemon-reload` applied.
- `cashpilot-nkn-agent.service` restarted once.
- Existing `cashpilot-worker` restarted exactly once; container was not recreated.
- Worker container ID, image digest, worker identity/key, compose file, and volumes remained unchanged.

## Verification snapshot

Final read-only snapshot completed at `2026-09-26T03:46:29Z` (UTC):

| Check | Result |
|---|---|
| Unit SHA-256 | `9ce6fccc3552130ba3ed810f7d4a3bfad8b4be5b9969503fb8a5e0aaaccd969a` |
| Helper service | `active` |
| `RuntimeDirectoryPreserve` | `yes` |
| Host runtime directory | device/inode `28:140377` |
| Container runtime directory | device/inode `28:140377` |
| Host `agent.sock` | device/inode `28:152235` |
| Container `agent.sock` | device/inode `28:152235` |
| Worker container | original ID; image `sha256:1b5468144c3c4e457279c8d6c9ec2a6fbef46c1759b32836607d15c1c4986005` |
| Worker health | `healthy` |
| Worker `/healthz` | HTTP `200` |
| Worker heartbeat | field present |
| Worker `/api/status` | HTTP `200` |
| Worker `/api/network/slots` | HTTP `200` |
| NKN helper inventory | HTTP `200`, `{"instances":[]}` |

## Verification note

The first wrapper run reported `post-verification` because it compared a `docker inspect .Mounts` JSON hash. The effective mount and inode checks were then verified directly and matched on host and container. The unit file was briefly restored for diagnosis, then re-applied from the backup and reloaded without another helper or worker restart. This did not change compose, container identity, image, data, or fleet volumes.

## Gate result

**PASS for the approved recovery gate.** The socket lifecycle fix is active and the existing worker can reach the helper socket. NKN inventory remains empty because no NKN deploy/retry was authorized or run. Stop here; wait for separate approval before any NKN slot retry or provider rollout.
