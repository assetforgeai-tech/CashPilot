# EarnApp

> **Category:** bandwidth | **Status:** Collector active; hosted runtime disabled
> **Website:** [https://earnapp.com](https://earnapp.com)

## Description

EarnApp proxy-only runtime with account-scoped identity and isolated
platform-specific canary lanes. Each node owns one exclusive residential
proxy.

## Current runtime policy (2026-08-29)

EarnApp hosted-runtime deployment is currently **disabled**. EarnApp terms
prohibit virtual machines, Docker/LXD containers and hosting services, so
CashPilot fails closed before selecting a worker, proxy, slot or lease for a
new VPS node. This is a compliance boundary, not a transient proxy or token
failure.

The encrypted Account Pool, collector, token-expiry metadata, historical
earnings and read-only inspection of existing nodes remain available. A
refreshed account token restores collection only; it does not re-enable hosted
runtime deployment. Existing nodes are immutable and must not be recreated,
migrated, rotated, unlinked or deleted by this policy change.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $0 (estimate) |
| Payout methods | paypal, crypto |
| Minimum payout | $2 |

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP required | Yes |
| VPS allowed | No |
| Devices per account | Not documented |
| Devices per IP | 1 |

## Setup

The historical platform-canary and provider-specific auto-deploy paths remain
in source for auditability, but the current policy gate disables them. Use the
Account Pool and collector screens for account maintenance and inspection.

1. Sign in to [EarnApp](https://earnapp.com) in a dedicated Chrome profile.
2. Use the CashPilot Provider Importer to import that profile's allowlisted
   `oauth-refresh-token` and `xsrf-token` into the encrypted Account Pool. Do
   not paste Google/Apple passwords, MFA codes, or raw cookies into Docker.
3. Ensure the Proxy Pool has a latest `earnapp_wss` probe with verdict
   `CID_SET`/`eligible`, a non-empty egress IP, `alive` status, `residential`
   IP type, and country `VN` for the Mac canary.
4. Do not deploy a hosted canary. New VPS deployment is blocked by policy.

Historical platform selection was immutable after a logical node was created:

- VN residential egress selects and persists MacOS or iOS.
- Non-VN residential egress selects Ubuntu in LXD and uses the official EarnApp
  package.
- Settings values `earnapp_lxd_cpu` and `earnapp_lxd_memory_mib` are
  authoritative for Ubuntu LXD limits; defaults are `1` CPU and `1024 MiB`.
- The worker accesses Ubuntu LXD only through the restricted
  `cashpilot-earnapp-agent` socket. It is never mounted to the raw LXD socket.

MacOS and iOS runtimes are separately authorized operator artifacts, not part
of the public CashPilot UI/worker release. Before deploying a fresh MacOS/iOS
node, build the exact external bundle with
`scripts/build_earnapp_canary_image.py`, verify its content-addressed manifest,
and preload the resulting image on that worker. CashPilot never pulls these
images from a public registry; a missing or wrongly labelled image fails before
an existing node, sidecar, volume, or lease is changed. The current pinned tags
are:

- `cashpilot/earnapp-mac-canary:asset-4a1e80cbb95d`
- `cashpilot/earnapp-ios:asset-061a2a32d69d`

Historical canary verification was successful only when the authenticated account route reports the
same device in `devices`, `device_statuses` reports it `online`, and a positive
workload/usage delta is observed. A running container or a local heartbeat alone
is not sufficient evidence.

## Verified live baseline

The v1.13.4 worker rollout was limited to `cashpilot-worker` on `test-sing`.
Chrome profile 40 remains authoritative. Authenticated collector evidence shows
both live devices online and not banned, with account totals online `2`, offline
`0`. Current-day qualified usage is positive for node 1 (`32,740,937 ms`) but
node 2 is near plateau (`18,142 ms`); this is a workload diagnostic, not proof
that Docker is the cause.

Preserve both successful nodes:

- logical node `earnapp-canary-test-sing-1`
- container `cashpilot-earnapp-canary-test-sing-1`
- sidecar `cashpilot-earnapp-canary-test-sing-1-egress`
- volume `earnapp-canary-test-sing-1-data`
- proxy lease `#12706`, egress `171.251.97.103`
- logical node `earnapp-recovery-test-sing-2`
- container `cashpilot-earnapp-recovery-test-sing-2`
- sidecar `cashpilot-earnapp-recovery-test-sing-2-egress`
- volume `earnapp-recovery-test-sing-2-data`
- final proxy lease `#12708`, egress `116.98.176.124`

The recovery node retained its account, generation, device ID, volume and
machine ID while rotating `12708 -> 12724 -> 12708`. The main process rejoined
the sidecar network namespace after each restart and retained egress, `eth0`,
routes and DNS. Existing nodes remain protected. Older iOS Docker and
Ubuntu-LXD canary notes are historical and are not deploy instructions under
the current policy.

## Operational contract

- EarnApp runs in `proxy` mode only; one node owns one residential egress.
- NKN, Mysterium, and other protected provider identities are outside this
  lane and are never recreated as part of an EarnApp retry.
- Existing runtime removal and lease release are blocked while hosted runtime
  is disabled. CashPilot does not automatically unlink or delete the remote
  EarnApp device.
- The encrypted Mac identity asset and writable `/etc/earnapp` volume are
  identity-critical. Do not delete the volume during a normal retry.
- Auto-deploy skips the disabled EarnApp runtime without contacting a worker or
  acquiring a proxy lease; other providers keep their existing queue behavior.
- The historical node-scoped proxy-rotation contract remains regression-tested,
  but automatic rotation and reconciliation are disabled for existing nodes.
  Heartbeats may record health evidence without mutating the lease.

## Token expiry

The importer records JWT/cookie expiry metadata without displaying token
values. The Settings account card marks tokens as healthy, expiring within
seven days, expiring within 24 hours, expired, or unknown. Refreshing a bound
Chrome profile is explicit and account-scoped; an unbound profile is never
automatically imported.

<!-- Everything above is derived from services/bandwidth/earnapp.yml.
     Add anything a user genuinely needs a human to explain BELOW this line:
     captcha quirks, account gotchas, what the dashboard calls things. -->
