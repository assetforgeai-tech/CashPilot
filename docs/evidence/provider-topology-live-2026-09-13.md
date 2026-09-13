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

## Remaining live gates

- Fresh direct-only, proxy-only, and hybrid canaries on current release.
- Owner-authenticated plan/deploy response for each lane.
- Live egress/lease/rotation/release and DNS/IPv6/UDP fail-closed evidence.
- Browser verification of `ready`, `partial`, and `blocked` states.
