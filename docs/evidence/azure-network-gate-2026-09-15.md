# Azure network gate

Captured 2026-09-15 after the `v1.51.15` worker rollout.

## Worker health

| Worker | Image | State | Managed containers | Restart observations |
| --- | --- | --- | ---: | --- |
| 118903 / East Asia | `cashpilot-worker:1.51.15` | running/healthy | 285 | Proxies-SX proxy-001/002 at restart count 10 |
| 118904 / Japan East | `cashpilot-worker:1.51.15` | running/healthy | 271 | ProxyBase direct instances have restart counts 1-3 |

## Host observations

Both hosts report kernel `6.17.0-1022-azure`, no IPv6 default route, resolver `127.0.0.53`, and host `OUTPUT` policy `ACCEPT` through UFW chains.

This is not sufficient evidence that every provider container is fail-closed. Container-level egress, DNS, DoH/DoT, UDP, IPv6, and direct-fallback checks remain required before a production-ready claim.

## Gate decision

`NOT_READY`: runtime health is positive, but network isolation and restart stability are incomplete. Do not generalize EarnApp or Spide evidence to other providers.
