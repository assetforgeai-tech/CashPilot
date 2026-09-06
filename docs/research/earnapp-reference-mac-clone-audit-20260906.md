# EarnApp reference macOS clone audit (2026-09-06)

## Source node

- UUID: `sdk-mac-66db858d1668e1e0fcc3da8af45247fa`
- Reference container: `earnapp-mac-n-e26d63`
- Reference volume: `earnapp-mac-n-e26d63-data`
- Image: `earnapp-2movn:bound`
- Image digest: `sha256:c42b5055e60102f57cb226c9d68194b4bb34e07dd94b37969ce262febd92b018`
- Binary version: `1.605.415`

The inspection was read-only. The source container, volume, identity, account,
and proxy lease were not modified.

## Transferable behavior

The reference runtime contains several behaviors that are useful to preserve
in the generic CashPilot runtime:

- persistent per-node `status`, `consent`, `tracking_id`, and UUID state;
- identity validation before starting the binary;
- a watchdog/restart loop around the EarnApp process;
- a separately validated machine identity and hostname bootstrap;
- restart persistence with one dedicated volume per node.

These behaviors must be generated from each node's own identity profile and
volume. They must not copy the reference node's state.

## Non-transferable state

The image is host-bound. It carries `BOUND_FP_HASH`, disk fingerprints, and a
fingerprint check that validates `/sys`, `/proc`, DMI data, and host disks.
Copying the image unchanged to another VPS would either fail the binding check
or incorrectly couple a new node to the source host. The encrypted profile,
UUID, CID files, consent timestamp, tracking ID, and proxy credentials are also
node-specific and must remain private.

## Version decision

The reference node uses the older `1.605.415` binary. CashPilot pins the newer
`1.660.577` binary, which changes `skip_local_addr`, Docker bridge filtering,
`tunnel_init` payload handling, and decline cooldown behavior. CashPilot keeps
the newer binary and ports only compatible lifecycle/bootstrap behavior.

## Current implementation consequence

The reference image is not promoted as a generic image. CashPilot's image
builder continues to generate a per-node profile, volume, proxy route, and
content-addressed runtime manifest. A future watchdog change must be tested
with a fresh canary and must not embed host fingerprints or source-node state.

## Test-US reboot finding

The upgraded worker rollout initially succeeded interactively, but the first
`vps-test-us` reboot restored `cashpilot-worker:1.21.14`. The cause was not an
EarnApp runtime or identity problem: `/etc/systemd/system/cashpilot-worker.service`
still referenced the old `docker-compose.worker.v1.21.14.override.yml`. The unit
was corrected to reference `docker-compose.worker.v1.21.17.override.yml`, then
reloaded and restarted without touching the six canary containers. Afterward the
worker reported `1.21.17`, was healthy, and heartbeat requests returned `200`.
All six canary container IDs, volumes, and start-time lineage remained intact.
