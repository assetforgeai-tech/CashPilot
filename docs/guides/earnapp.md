# EarnApp

> **Category:** bandwidth | **Status:** Active
> **Website:** [https://earnapp.com](https://earnapp.com)

## Description

EarnApp proxy-only runtime with account-scoped identity and an explicit Mac-emulation canary lane. Each node owns one exclusive residential proxy.

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

EarnApp has an owner-controlled **Mac-emulation canary** and an implemented
provider-specific auto-deploy lane. The first live device is linked and verified
on the EarnApp dashboard. Keep the global `Deploy to stable workers` setting
disabled until the pending UI/worker release and fresh-worker recovery matrix
have passed; implementation alone does not authorize a fleet rollout.

1. Sign in to [EarnApp](https://earnapp.com) in a dedicated Chrome profile.
2. Use the CashPilot Provider Importer to import that profile's allowlisted
   `oauth-refresh-token` and `xsrf-token` into the encrypted Account Pool. Do
   not paste Google/Apple passwords, MFA codes, or raw cookies into Docker.
3. Ensure the Proxy Pool has a latest `earnapp_wss` probe with verdict
   `CID_SET`/`eligible`, a non-empty egress IP, `alive` status, `residential`
   IP type, and country `VN` for the Mac canary.
4. Deploy exactly one owner-authorized canary logical node. CashPilot assigns
   one exclusive proxy and persists one Mac identity/profile per logical node.

Platform selection is immutable after the logical node is created:

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

The canary is successful only when the authenticated account route reports the
same device in `devices` and `device_statuses` reports it `online`. A running
container or a local heartbeat alone is not sufficient evidence.

## Operational contract

- EarnApp runs in `proxy` mode only; one node owns one residential egress.
- NKN, Mysterium, and other protected provider identities are outside this
  lane and are never recreated as part of an EarnApp retry.
- Removing a failed canary may release only that canary's lease. CashPilot does
  not automatically unlink or delete the remote EarnApp device.
- The encrypted Mac identity asset and writable `/etc/earnapp` volume are
  identity-critical. Do not delete the volume during a normal retry.
- Auto-deploy runs EarnApp after NKN and generic providers, one node at a time.
  A failed EarnApp node is recorded and skipped instead of blocking later work.
- A node-scoped proxy failure may rotate only that node's lease through the
  server-authoritative CAS flow. Account, platform, identity and volume stay
  unchanged, and `RECOVERY_HOLD` remains one hour.

## Token expiry

The importer records JWT/cookie expiry metadata without displaying token
values. The Settings account card marks tokens as healthy, expiring within
seven days, expiring within 24 hours, expired, or unknown. Refreshing a bound
Chrome profile is explicit and account-scoped; an unbound profile is never
automatically imported.

<!-- Everything above is derived from services/bandwidth/earnapp.yml.
     Add anything a user genuinely needs a human to explain BELOW this line:
     captcha quirks, account gotchas, what the dashboard calls things. -->
