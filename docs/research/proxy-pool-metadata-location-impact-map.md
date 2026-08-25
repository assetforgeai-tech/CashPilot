# Proxy Pool Metadata and Location Impact Map

Date: 2026-08-25

Scope: metadata enrichment and Proxy Pool presentation only. This change does
not alter provider runtime, worker behavior, credentials, identities, wallets,
proxy assignments, leases, or live provider containers.

## Verified failure

The read-only diagnostic snapshot that motivated this change found 1,004 proxy
rows, 1,000 alive rows, and 1,000 rows with an egress IP. Country metadata and
IP type were still pending on 739 rows. The old UI-side lookup called the
metadata services from the `cashpilot-ui` network namespace: `ipwho.is` returned
HTTP `429`, while the regional `ipapi.is` hosts failed to connect. The old
helper converted both outcomes to an empty result, so the dashboard could only
show `Metadata pending` and could not distinguish a provider limit from a bad
proxy or a transient connection error.

The same metadata requests routed through the proxy being inspected returned
HTTP `200` responses with country code and IP-quality evidence. The proxy-routed
path is therefore the authoritative repair path. It runs at bounded concurrency
and records source status and `Retry-After` evidence without logging proxy
credentials or raw URLs containing credentials.

## Data contract

| Field | Contract | Use |
| --- | --- | --- |
| `country_code` | ISO alpha-2 uppercase code (`VN`, `US`, `GB`, ...) | Authoritative machine key for future EarnApp location selection and grouping |
| `country_name` | Raw provider evidence | Preserved evidence; not a lease predicate |
| `location` in the read model | Canonical code or explicit state (`Egress unresolved`, `Metadata pending`, `Generic check failed`) | Operator-facing filter/sort value |
| `geo_source`, `geo_confidence`, `geo_checked_at` | Source and freshness evidence | Auditability and retry decisions |
| `ip_type`, `ip_type_source`, `ip_type_confidence`, `ip_type_checked_at` | Quality evidence (`residential`, `datacenter`, `hosting`, `proxy`, `vpn`) | Operator display and future provider qualification |

Existing raw rows are not bulk-normalized. The read model maps known aliases
such as `Vietnam`/`Viet Nam` to `VN`, while retaining the original
`country_name`. Unknown names remain evidence rather than being guessed into a
code.

## Refresh boundary

`POST /api/proxy-pool/metadata-refresh` is owner-only, accepts at most 100
selected IDs, deduplicates by egress IP, and caps metadata concurrency at two.
It updates only geo/IP-type fields when valid evidence exists. It does not run
generic probes, EarnApp probes, duplicate reconciliation, proxy rotation,
assignment, or lease/release operations. A canary for one alive, unleased,
canonical proxy must succeed before bounded batches are considered.

The ordinary generic and EarnApp recheck paths reuse the source-aware helper for
their already-discovered egress IPs. When a lookup is explicitly routed through
a proxy, an empty routed result is not retried directly from the UI server; that
would reintroduce the observed rate-limit and misattribution failure.

## Protected boundaries

The following remain unchanged and are outside this work:

- worker image, heartbeat, deployment orchestration, and sidecar contracts;
- provider catalog/runtime/collector code, including all `PROTECTED_DONE`
  providers and the retired Grass boundary;
- proxy credentials, raw import evidence, proxy assignments, scoped leases,
  provider masks, rotation and release/reclaim logic;
- MYST/NKN wallets, identities, volumes, ChainDB and direct-only runtime;
- live containers and databases except the explicitly approved metadata fields
  during a canary/bounded refresh.

Any future shared-module change must provide a new impact map, regression tests,
an isolated canary, and explicit approval.
