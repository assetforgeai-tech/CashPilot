# EarnApp

> **Category:** bandwidth | **Status:** Collector active; Ubuntu x64/LXD platform restricted
> **Website:** [https://earnapp.com](https://earnapp.com)

## Description

EarnApp proxy-only runtime with account-scoped identity and isolated
platform-specific canary lanes. Each node owns one exclusive residential
proxy.

## Current runtime policy (2026-08-29)

EarnApp runtime deployment is **platform restricted**. CashPilot permits only
the official Linux x64 package through the dedicated Ubuntu LXD lane. The
official installation guide says EarnApp supports x64 Linux on a 64-bit OS,
identifies Ubuntu 20.04 as its tested distribution, and installs a service that
starts automatically after reboot.

The encrypted Account Pool, collector, token-expiry metadata, historical
earnings and read-only inspection of existing Apple nodes remain available.
MacOS/iOS emulation, the generic catalog/Docker route, raw worker Docker deploy,
and caller-supplied Ubuntu metadata on generic routes remain blocked. This
source policy change does not release, deploy, migrate, rotate or otherwise
alter the existing live baseline.

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
| CashPilot runtime | Official Linux x64 in dedicated Ubuntu LXD only |
| Devices per account | Not documented |
| Devices per IP | 1 |

## Setup

Use the Account Pool for account credentials and the dedicated EarnApp Ubuntu
lane for runtime planning. Do not submit EarnApp through the generic provider
deploy endpoint or the generic worker Docker endpoint.

1. Sign in to [EarnApp](https://earnapp.com) in a dedicated Chrome profile.
2. Use the CashPilot Provider Importer to import that profile's allowlisted
   `oauth-refresh-token` and `xsrf-token` into the encrypted Account Pool. Do
   not paste Google/Apple passwords, MFA codes, or raw cookies into Docker.
3. Ensure the Proxy Pool has a latest `earnapp_wss` probe with verdict
   `CID_SET`/`eligible`, a non-empty egress IP, `alive` status, `residential`
   IP type, and a non-VN country for an Ubuntu node.
4. Configure `earnapp_lxd_cpu` and `earnapp_lxd_memory_mib`; defaults are `1`
   CPU and `1024 MiB`.
5. Use only the dedicated server/worker Ubuntu LXD contract. The official
   installer remains pinned and verified by the restricted host helper.

Current platform selection is immutable after a logical node is created:

- Non-VN residential egress selects Ubuntu in LXD and uses the official EarnApp
  package.
- Settings values `earnapp_lxd_cpu` and `earnapp_lxd_memory_mib` are
  authoritative for Ubuntu LXD limits; defaults are `1` CPU and `1024 MiB`.
- The worker accesses Ubuntu LXD only through the restricted
  `cashpilot-earnapp-agent` socket. It is never mounted to the raw LXD socket.

MacOS and iOS artifacts are retained only as historical forensic evidence. They
are not deployment-authorized by the current source policy. Their historical
pinned tags were:

- `cashpilot/earnapp-mac-canary:asset-4a1e80cbb95d`
- `cashpilot/earnapp-ios:asset-061a2a32d69d`

Runtime closeout is successful only when the authenticated account route reports the
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
routes and DNS. Existing Apple nodes remain protected. Older iOS Docker notes
are historical and are not deploy instructions under the current policy. The
Ubuntu lane is enabled in source but has not been released, deployed or
live-closed by this gate change.

## Operational contract

- EarnApp runs in `proxy` mode only; one node owns one residential egress.
- NKN, Mysterium, and other protected provider identities are outside this
  lane and are never recreated as part of an EarnApp retry.
- Ubuntu lifecycle, recovery, removal and proxy rotation use the dedicated LXD
  endpoints plus generation/device CAS. Removal must complete at the worker
  before the server releases the scoped lease and finalizes bookkeeping.
- The Ubuntu identity and `/etc/earnapp` guest state remain identity-critical;
  suspend, resume and proxy rotation preserve them.
- Auto-deploy invokes the dedicated Ubuntu planner sequentially and excludes
  EarnApp from the generic Docker catalog queue. A failed node must not block
  later providers.
- Stale recovery and replacement tickets apply only to Ubuntu nodes. MacOS/iOS
  lifecycle, recovery, removal and proxy mutation remain blocked.

## Token expiry

The importer records JWT/cookie expiry metadata without displaying token
values. The Settings account card marks tokens as healthy, expiring within
seven days, expiring within 24 hours, expired, or unknown. Refreshing a bound
Chrome profile is explicit and account-scoped; an unbound profile is never
automatically imported.

<!-- Everything above is derived from services/bandwidth/earnapp.yml.
     Add anything a user genuinely needs a human to explain BELOW this line:
     captcha quirks, account gotchas, what the dashboard calls things. -->
