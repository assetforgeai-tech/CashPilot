# Azure network gate

Captured 2026-09-15 after the `v1.52.0` worker rollout.

## Worker health

| Worker | Image | State | Managed containers | Restart observations |
| --- | --- | --- | ---: | --- |
| 118903 / East Asia | `cashpilot-worker:1.52.0` | running/healthy | 285 | 285/285 running; refreshed Proxies-SX proxy-001/002 restart count 1 |
| 118904 / Japan East | `cashpilot-worker:1.52.0` | running/healthy | 272 | 272/272 running; ProxyBase direct instances have historical restart counts 1-3 |

## Host observations

Both hosts report kernel `6.17.0-1022-azure`, no IPv6 default route, resolver `127.0.0.53`, and host `OUTPUT` policy `ACCEPT` through UFW chains.

This is not sufficient evidence that every provider container is fail-closed. Container-level egress, DNS, DoH/DoT, UDP, IPv6, and direct-fallback checks remain required before a production-ready claim.

## Fresh provider authority

CashPilot authority after rollout reports 40 Spide instances (20 direct, 20 proxy), all running, and 20 Proxies-SX instances, all running. A fresh Spide dashboard pagination probe exceeded the bounded 300-second authority check and is not treated as proof of current provider-dashboard state.

The two refreshed East Asia Proxies-SX containers are running with restart count 1, but both still time out while downloading `https://agents.proxies.sx/peer/reference-sdk.js`. This remains an unresolved provider bootstrap/egress issue; the containers are not counted as earning evidence.

## Gate decision

`NOT_READY`: runtime health is positive, but network isolation and restart stability are incomplete. Do not generalize EarnApp or Spide evidence to other providers.
