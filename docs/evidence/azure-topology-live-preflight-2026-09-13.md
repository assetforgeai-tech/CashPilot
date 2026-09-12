# Azure topology live preflight

Date: 2026-09-13

## Workers

- East Asia: `20.187.79.110`, worker image `ghcr.io/assetforgeai-tech/cashpilot-worker:1.39`, healthy.
- Japan East: `20.210.93.220`, worker image `ghcr.io/assetforgeai-tech/cashpilot-worker:1.39`, healthy.
- Docker server: `29.1.3`.
- `cashpilot-network-slots.service`: active on both workers.
- `cashpilot-worker.service`: active on both workers.

## Slot evidence

- Both workers expose `/network/public-ip-slots.json` through the read-only
  `cashpilot_public_ip_slots` Docker volume.
- Each manifest contains 10 slots, `ipv4-001` through `ipv4-010`.
- All 10 slots report `route_ready=true`.
- Each slot has a distinct Azure public IPv4, private source address, gateway,
  dedicated Docker network, and bridge subnet.
- The host has corresponding secondary private addresses on `eth0`; Azure's
  public addresses are represented by the slot manifest rather than assigned
  as host public addresses.

## Scope and gates

This is read-only preflight evidence. No provider, container, lease, route, or
firewall mutation was performed. It proves the prerequisites for direct-only
and hybrid canaries, not successful provider earning or complete leak absence.
Required next evidence: one direct-only canary, one hybrid canary, per-lane
egress/DNS/IPv6/UDP/DoH probes, restart/reboot persistence, lease rotation, and
failure isolation.

## Heartbeat probe

- Worker health endpoint `http://127.0.0.1:8081/api/health` returned `200` on
  both workers and identified the expected worker IP.
- Worker logs show successful POST heartbeats to the CashPilot server at roughly
  60-second intervals on both workers.
- This proves worker liveness only; it does not prove provider-node health.
