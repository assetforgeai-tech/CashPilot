# EarnApp reference macOS clone audit (2026-09-06)

## Live evidence, 2026-09-07

UI commit `133b4b0` passed 2623 tests (9 skipped), Ruff check and format.
UI image `1.21.25` was published and its lifecycle code inspected before a
scoped deployment in `/opt/cashpilot`. Mount mappings and admin key matched
the previous container; authenticated `/api/workers` returned HTTP 200.
The build workflow's tag verification failed only because worker `1.21.25`
was deliberately not built. The live worker remains `1.21.21`.

Both authorized macOS canaries were removed through `/api/remove` on worker
92161. Each returned HTTP 200 with `main_present=false` and
`sidecar_present=false`. Database assignments became PLANNED with no worker
or proxy; accounts, UUIDs and volumes were retained. Both were then recreated
through the supported canary deployment route using the existing pinned
runtime. This recreation is not a promotion of the reference runtime.

| Node suffix | New container ID | Expected and observed egress |
| --- | --- | --- |
| macos-01 | `552edcb55f174d61a20118a4be140477a04c63f23b7ca15d6a744553af58f9bb` | `116.98.226.84` |
| macos-02 | `335f96f60529810a4b4c48ae1d1b359fdf128d417a20d09c6367f269d44d6b76` | `171.251.99.76` |

Both are ACTIVE in the database, with matching container IDs, zero restarts
and no interface errors in the inspected startup logs. Node 01's HTTP caller
timed out during the long workload verification stage after deployment;
the runtime and bookkeeping were separately confirmed present. Running and
matching egress do not establish usage. Latest inspected account snapshots
at 00:10 UTC still reported `usage_current=0` for both UUIDs, with the next
earnings update around 01:00 UTC. Some historical usage totals equaled uptime;
those totals are not accepted as fresh workload evidence.

Fresh reference inspection confirms image digest
`sha256:c42b5055e60102f57cb226c9d68194b4bb34e07dd94b37969ce262febd92b018`,
SOCKS5, `/usr/local/bin/bound-entrypoint`, and executable SHA256
`3333e8dd1e1a5433d79542ad646edcf07256e3f9fee05e14735e61e606a374d0`.
Its supervisor validates per-node plaintext identity, seeds persistent state,
applies host bootstrap, and launches the entrypoint. CashPilot instead loads
its own encrypted identity through `boot.js`. The reference host bootstrap
adds a LAN alias plus an SNAT rule; CashPilot's inspected bootstrap adds an
alias without that rule. These differences have not yet been isolated in a
controlled runtime comparison. The reference's recent logs alone do not
establish a fresh per-device usage delta. EarnApp closeout remains unverified.

Further raw inspection showed node 02's container metadata is equivalent to
node 01's: same verified image and runtime labels, distinct encrypted profile,
UUID, account, proxy credentials, and expected egress. Its process emits
repeated `tunnel_init` and `register_client` reports, while EarnApp's account
API continues to return `online=true`, `uptime=0`, and `earned=0`. The worker
heartbeat remains HTTP 200. This is a provider-side per-device accounting
discrepancy; changing local traffic, identity, or reference credentials would
destroy the controlled comparison and is intentionally not done.

## Source node

## Follow-up evidence, 2026-09-07

After the `1.21.27` worker rollout, node 02 was restarted with its retained
volume. The new bootstrap wrote `ver=1.660.577` automatically and the process
sent repeated `tunnel_init`, `register_client`, and proxy heartbeat reports
with HTTP 200 responses. Its proxy egress remained `171.251.99.76` and DB
lease/heartbeat state remained healthy. The account collector returned `status=ok`.

The account API still reported node 02 online but with `uptime=0`,
`earned=0`, and empty bandwidth. Node 01 continued to report `earned=0.102`
under `qualified_uptime`. Container metadata, image, identity, UUID, account,
proxy type, and expected egress matched the deployed contract. This isolates
the remaining discrepancy to EarnApp's per-device backend accounting or
registration state; no credential, identity, or reference state was changed.

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

## Usage-positive reference comparison

The operator confirmed that the source UUID is usage-positive on the upgraded
reference VPS. Read-only logs show the source route exits through `69.215.151.72`
(`US`) and differs from the current test-US macOS canaries in several protocol
inputs:

| Field | Reference source | CashPilot macOS canary |
| --- | --- | --- |
| CPU/OS profile | `arm64`, macOS `11.4` | `x86_64`, macOS `14.6.1` |
| EarnApp binary | `1.605.415` | `1.660.577` |
| tunnel `appid` | `mac_com.earnapp` | stable alias emitted by `1.660.577` |
| tunnel payload | includes `makeflags`, `sdk_version`, `confdir`, `gw_ip`, `http3`, `is_swift`, `idle=false` | newer payload omits deprecated fields and uses the hardened contract |
| observed country | `US` | `VN` |

This is evidence for a controlled differential canary, not permission to copy the
source UUID, encrypted profile, CID, consent, tracking state, proxy credential,
or host-bound image. Production remains on the newer binary until a separate
canary proves which variable affects usage.

## Controlled binary differential

A bounded test on `sdk-mac-ecb0b1fda1d61d79f09bfee6138643ea` changed only
the executable from `1.660.577` to the verified `1.605.415` bytes while
preserving the node UUID, account, proxy, volume, container and generated
identity profile. The older executable started and connected, but immediately
selected the real Docker address `172.17.0.3` for agent tunnel initialization
and logged `interface not found for 172.17.0.3`. The current executable instead
uses the emulated `en0` / `10.255.255.1` identity path without that warning.

The node was restored to `1.660.577` after the observation. No identity,
account assignment, proxy lease or volume was replaced. This rejects an
unqualified rollback to `1.605.415`: its positive result on the source VPS
depends on more than the binary alone, and the rollback reintroduces the exact
Docker-interface mismatch fixed by the current release.
