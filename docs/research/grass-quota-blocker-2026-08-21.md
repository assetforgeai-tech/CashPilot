# Historical Grass quota diagnostic

> Historical, redacted evidence only. Grass was subsequently removed from the
> CashPilot product. This document is not deployment guidance and does not
> authorize restoring, registering, or operating Grass nodes.

Date verified: 2026-08-21

Environment: `vps-test-sing`

Account evidence source: Chrome profile 40

## Finding

The isolated canary could not become Connected because the Grass API rejected
device registration with HTTP `403` and `device_quota_exceeded`. The account
reported `deviceCount: 100` at the time of the test.

This ruled out the leading infrastructure hypotheses for that experiment:

- DNS resolution worked over IPv4.
- HTTPS reached the official API.
- The proxy egress probe returned an address.
- The Desktop session was authenticated in noVNC.
- The local profile contained session fields, but the API never issued the
  device-registration identity fields.

Local process state or a locally written `CONNECTED` value was therefore not
authoritative evidence of network registration. Copying another profile,
changing DNS, rotating the proxy, or retrying registration could not remove an
account-side quota response.

## Safety record

- The previously protected node was not restarted, recreated, or rotated during
  this diagnostic.
- The canary used an isolated container, volume, identity, sidecar, and proxy
  lease.
- Account email, tokens, device keys, cookies, and egress addresses are omitted.
- No guessed `DELETE` endpoint was called to reclaim an account device.

## Superseding decision

The later product decision removed Grass from the active catalog and runtime.
See [Provider removal decision: Grass](provider-removal-grass-2026-08.md).
No quota-reclaim or retry action remains open in the current CashPilot product.
