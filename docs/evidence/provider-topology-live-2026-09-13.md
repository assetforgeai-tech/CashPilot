# Provider Topology Live Evidence

## Scope

Read-only SSH inspection. No provider/container mutation. Azure CLI was not used.

## Historical network evidence

- Existing iOS and macOS EarnApp proxy lanes had distinct IPv4 egresses:
  `116.98.229.8` and `14.243.208.175`.
- Both used loopback DNS, redsocks, DoH helper, explicit IPv6 drop chains, and
  terminal output drops. IPv6 enforcement was observed, not treated as a full
  application-level leak proof.
- Earlier worker image was `1.33.3`, older than the then-current release; this
  evidence did not prove production readiness.

## 2026-09-13 Azure worker preflight

- East Asia runs healthy `cashpilot-worker:1.45`, one EarnFM direct lane, and
  legacy NKN LXD instances.
- Japan East runs healthy `cashpilot-worker:1.45`; no provider container was
  visible in the inspected inventory.
- Both hosts expose ten private NKN NAT source routes. These are not public
  IPv4 slot evidence for provider planning.
- Duplicate worker registrations exist per URL: East Asia `112494` offline /
  `118903` online; Japan East `112444` offline / `118904` online.
- Old registrations remain untouched. API/UI now annotate superseded rows and
  count physical workers separately.

## Historical release evidence

- PR #317 merged as `e943d3b1`; release `v1.42.0` published.
- PR #318 merged as `0145a023`; CI passed the recorded gates.
- Current local release-pin tests cannot resolve fork ref `1.45`; this is
  release-ref environment drift, not a topology failure.

## 2026-09-13 release and redeploy

- Release `v1.46.0` completed Tests, CodeQL, Lint, Catalog Check,
  Documentation, and Auto Release successfully.
- Both Azure workers were upgraded from `cashpilot-worker:1.45` to
  `cashpilot-worker:1.46`, retaining existing worker data, slot volume, Docker
  socket, and provider containers. Both report `running|healthy`, restart
  policy `always`, and heartbeat HTTP 200. Worker image digest:
  `sha256:1acceed5ffb9da86ea93fe30f5a2d8a4fc1ff59509e1b7d6691e4c934e1ed84e`.
- The 4gmt server UI and worker were upgraded to `1.46`; both report
  `running|healthy`. UI digest:
  `sha256:be16aa7eea0e2c13e456196ac44dab83587e4c88b02eba1663160477695d7245`.
  SQLite integrity returned `ok` before deployment completion.
- No provider container was removed or recreated during the worker/server
  upgrade.

## Remaining live gates

- Fresh direct-only, proxy-only, and hybrid canaries on current release.
- Owner-authenticated plan/deploy response for each lane.
- Live egress/lease/rotation/release and DNS/IPv6/UDP fail-closed evidence.
- Browser verification of `ready`, `partial`, and `blocked` states.

## 2026-09-13 post-redeploy contract check

- Server-side catalog now reports EarnApp `slot_proxy` with
  `bind_capacity_slot`, `offline=restart`, `usage_stalled=restart`, and
  `banned=restart`.
- `iproyal` reports `provider_private` allocation with
  `mask_and_replace`; its offline/usage/banned actions remain `observe`.
- `earnfm` reports independent `bind_public_ipv4_slot` and
  `bind_capacity_slot` lanes; offline/usage/banned remain `observe`.
- `mysterium` and `nkn` remain dedicated direct adapters, not generic slot
  planners.
- Read-only database check showed account `2` active and 13 active EarnApp
  leases. A legacy logical-node row exists without a matching provider-instance
  row; this is reconciliation drift and must be resolved through the existing
  owner-authorized reconciliation path, not an automatic delete.
- Fresh owner-authorized direct/proxy/hybrid deploy and egress evidence remains
  pending. No canary was started from an unverified or missing proxy capacity
  response.

## Current capacity plan (read-only)

- Worker `118903` and `118904` each expose 10/10 route-ready public IPv4 slots
  and 768 scoped proxy-capacity units. Plans are `ready`: EarnFM hybrid
  desired `20`, IPRoyal proxy-only desired `10`, Packetstream proxy-only
  desired `10` per worker.
- Only one existing provider container is present on East Asia: an EarnFM
  direct lane. Japan East has no provider container. This confirms planning
  capacity, not successful provider deployment or egress.
- Host kernel is `6.17.0-1022-azure`; this is expected worker-host metadata and
  is not proof that a provider binary is correctly masked. Container-level
  uname and direct/IPv6/DNS/UDP probes remain required.

## Direct-lane canary

- Existing East Asia EarnFM direct instance
  `cashpilot-earnfm-direct-w118903-ipv4-001` is attached to
  `cashpilot-direct-ipv4-001` with container IPv4 `10.253.1.2`.
- The slot manifest declares public IPv4 `13.70.42.190`; an independent HTTPS
  egress request from inside the container returned exactly `13.70.42.190`,
  while the host primary egress is `20.187.79.110`.
- A controlled restart returned the same container network address and exact
  slot egress. This verifies direct-lane route binding and restart persistence;
  it does not yet prove host reboot persistence.

## Proxy-lane canary

- A bounded PacketStream proxy canary was deployed on worker `118904` with
  `proxy_desired=1`. The worker created the provider container plus its
  `sing-box` egress sidecar, both with `restart=always`.
- The provider reported `Unable to connect to validation server`; the sidecar
  repeatedly reported DNS resolution failure for the leased upstream proxy
  hostname. This is a real proxy-health failure, not permission to fall back to
  the host's direct route.
- The required follow-up is provider-scoped mask-and-replace/reconciliation,
  followed by a second eligible proxy probe. The failed canary is not evidence
  of production readiness.
- After the failure was captured, both canary containers were stopped and the
  PacketStream lease was released through the provider-scoped API. The failed
  endpoint remains masked only for PacketStream; no other provider allocation
  was changed.
