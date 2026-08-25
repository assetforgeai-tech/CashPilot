# Proxy Pool Metadata and Location Live Closeout

Date: 2026-08-25

## Scope

This closeout covers the released Proxy Pool metadata/location UI and the
bounded live metadata refresh that followed it. It does not change provider
runtime, worker behavior, credentials, identities, wallets, assignments,
leases, proxy credentials, or live provider containers.

The screenshot that motivated this work was a pre-closeout view. Its large
`Metadata pending`, `unknown`, and unresolved counts must not be compared with
the final read model without also checking the capture time and release line.

## Release and deployment evidence

- Proxy Pool metadata/location clarity merged in PR #38 at
  `30ab8a2b4e4915deba9ed216e1b6fa7c47ea91ad`.
- Auto Release run `32837209953` completed successfully and published
  `v1.10.0`.
- The live `cashpilot-ui` container is healthy at UI digest
  `sha256:f62032cc8e0cac986c02ed2b1760b1f175942a4a0a2b4a9309d1c6f6828798c0`,
  with restart count `0`.
- Only `cashpilot-ui` was redeployed. `cashpilot-worker` remains healthy on
  its existing local image, container, start time, and restart count; no
  worker/provider redeploy was performed for this closeout.
- The live database integrity check remains `ok`; no schema or data migration
  was introduced by the UI/documentation closeout.

## Final read-only inventory snapshot

The authenticated API snapshot read all `1,004` rows over `11` bounded pages
and found stable totals and unique row IDs. No endpoint credentials or raw
proxy URLs are recorded here.

| Signal | Count |
| --- | ---: |
| Inventory | 1,004 |
| Generic live / dead | 1,000 / 4 |
| Egress known / unresolved | 1,000 / 4 |
| Location pending | 0 |
| IP type pending | 0 |
| Metadata pending | 0 |
| Duplicate egress rows | 161 |
| Canonical available | 839 |
| EarnApp eligible | 306 |
| EarnApp leaseable | 273 |
| EarnApp checked / not checked | 881 / 119 |
| EarnApp skipped (generic failure) | 4 |
| Active assignments / scoped leases | 0 / 0 |

Protocol/type counts are HTTP `1,004`, SOCKS5 `0`, residential `1,000`, and
unknown `4`. The four unknown type rows are exactly the four generic-dead rows
with no authoritative egress; they remain unresolved by design.

## Location contract for EarnApp

- `country_code` is the authoritative ISO alpha-2 machine key. The current
  known egress set is `VN` for `1,000` rows.
- The UI derives a readable label (`Vietnam`) from the code. It must not use a
  free-form `country_name` as the lease predicate.
- The location filter and exports use the canonical code/read-model contract;
  unresolved states remain distinct (`Generic check failed`, `Egress
  unresolved`, or `Metadata pending`).
- `country_name`, source, confidence, and timestamps remain evidence for audit
  and freshness decisions. They are not authorization to lease a proxy.

EarnApp lease selection remains independent of the display label: a proxy must
also be alive, have a known egress, be canonical, be unassigned/unleased, and
have the latest `CID_SET` eligible EarnApp evidence. Location metadata alone
never makes a proxy EarnApp-eligible.

## Refresh evidence and boundaries

- A one-proxy canary persisted country and IP-type evidence through the proxy
  route; the dashboard displayed `Vietnam` and `residential`.
- Bounded metadata-only batches then reached zero pending location/type for
  all rows with known egress. A fallback source produced valid evidence when a
  primary source returned a rate-limit response; no rate-limit failure was
  treated as fabricated metadata.
- The four generic-dead rows were not forced through metadata lookup because
  they have no authoritative egress IP.
- No generic recheck, EarnApp recheck, rotation, lease/release, assignment,
  duplicate cleanup, credential change, wallet operation, or provider runtime
  action was performed as part of the metadata closeout.

## Protected baseline

All `PROTECTED_DONE` providers, the worker image/runtime, MYST/NKN wallets and
identities, volumes, direct-only contracts, proxy lease guards, and live
provider containers remain outside this change. Any future location-based
EarnApp allocation change requires a new impact map, regression tests, a
separate canary, and explicit approval.

## Remaining data-quality item

There is no remaining location or IP-type metadata backlog for rows with
known egress. The only unresolved rows are the four generic-dead proxies; the
safe next action is to investigate or recheck those rows separately if needed,
without assigning them or inventing location/type data.
