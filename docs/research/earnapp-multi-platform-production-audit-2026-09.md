# EarnApp Multi-Platform Production Audit

Updated: 2026-09-01

## Scope

This audit covers only the EarnApp production-completion branch. NKN, MYST,
Grass-removal history, and other `PROTECTED_DONE` providers are out of scope.

## Geo/runtime matrix

| Proxy qualification | Platform | Runtime | Account evidence required |
|---|---|---|---|
| VN + residential | macOS | dedicated Docker artifact | exact UUID, online, positive usage |
| VN + residential | iOS | dedicated Docker artifact | exact UUID, online, positive usage |
| non-VN + residential | Ubuntu 22.04 profile | dedicated Docker artifact | exact UUID, online, positive usage |

Non-residential, missing-country, duplicate-egress, blocked, or unprobed
proxies are not eligible. Each account/node owns an exclusive residential
egress.

## Identity contract

Fresh Ubuntu profiles include the forensic fields `host.json`, `host.serial`,
machine-id, hostname, interface, release, model, CPU and memory metadata. The
device ID is a fresh `sdk-node-` plus 32 lowercase hexadecimal characters; the
persistent `/etc/earnapp` volume is the identity boundary. The entrypoint also
removes the Docker marker, persists machine-id/tracking state, invokes
`earnapp-host ensure/apply` when present, validates egress, then performs
control-plane registration before starting the official runtime.

Existing profile bytes are never rewritten by a canary or proxy rotation.

## Proxy rotation contract

Changing a proxy is not a sidecar-only restart for EarnApp. The worker stages
and probes the candidate route, then recreates only the EarnApp main container
while retaining image, environment, labels, identity volume, device ID and
resource limits. The old container is kept under a temporary name until the
replacement starts healthy; failed creation restores the old name and starts
the old container. Server CAS/finalize remains authoritative for lease commit.

## Link retry contract

Verification calls are serialized per account. Every retry uses at least a
five-second relay. A burst of five attempts is followed by a 300-second
cooldown, then the loop may continue. The exact UUID must match; a different
dashboard row never satisfies the node.

## Canary matrix and closeout

Canaries are sequential, never parallel, with fresh logical ID, volume,
identity, proxy lease and egress:

- 3 macOS nodes on distinct VN residential proxies.
- 3 iOS nodes on distinct VN residential proxies.
- 3 Ubuntu nodes on distinct non-VN residential proxies.

For every node, record S1 `install_device`, S2 authenticated link, S3 exact
UUID in account `devices`, and S4 online/not-banned plus positive usage or
earnings delta. A local process/heartbeat alone is insufficient. A failed node
is isolated and must not block later nodes.

## Rollback and protection

Rollback is node-local. It preserves identity volume, credentials, account
binding and leases until the worker confirms removal or transaction rollback.
Protected provider/node aliases are rejected before worker mutation. No bulk
cleanup or catalog redeploy is allowed as part of canary work.

## Verification status

Source verification for this branch: focused EarnApp/proxy tests `411 passed`,
full suite `2435 passed, 8 skipped`, Ruff, compileall and `git diff --check`
passed. Live release/deploy and the 3x3 canary matrix require fresh VPS and
account-dashboard evidence.
