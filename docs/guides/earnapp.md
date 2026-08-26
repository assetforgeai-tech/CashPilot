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

EarnApp is currently exposed through an owner-controlled **Mac-emulation
canary** lane. Generic auto-deploy is intentionally disabled until the first
live device has been linked and verified on the EarnApp dashboard.

1. Sign in to [EarnApp](https://earnapp.com) in a dedicated Chrome profile.
2. Use the CashPilot Provider Importer to import that profile's allowlisted
   `oauth-refresh-token` and `xsrf-token` into the encrypted Account Pool. Do
   not paste Google/Apple passwords, MFA codes, or raw cookies into Docker.
3. Ensure the Proxy Pool has a latest `earnapp_wss` probe with verdict
   `CID_SET`/`eligible`, a non-empty egress IP, `alive` status, `residential`
   IP type, and country `VN` for the Mac canary.
4. Deploy exactly one owner-authorized canary logical node. CashPilot assigns
   one exclusive proxy and persists one Mac identity/profile per logical node.

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

## Token expiry

The importer records JWT/cookie expiry metadata without displaying token
values. The Settings account card marks tokens as healthy, expiring within
seven days, expiring within 24 hours, expired, or unknown. Refreshing a bound
Chrome profile is explicit and account-scoped; an unbound profile is never
automatically imported.

<!-- Everything above is derived from services/bandwidth/earnapp.yml.
     Add anything a user genuinely needs a human to explain BELOW this line:
     captcha quirks, account gotchas, what the dashboard calls things. -->
