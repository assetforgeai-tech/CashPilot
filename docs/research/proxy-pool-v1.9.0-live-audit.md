# Proxy Pool v1.9.0 Live Audit

Date: 2026-08-25

Scope: read-only verification after the `v1.9.0` UI release and the addition
of the Proxy Pool import protocol selector. The only live mutation in this
closeout was the explicitly scoped `cashpilot-ui` recreate. No proxy row was
imported, rechecked, deleted, rotated, leased, released, assigned, or
normalized during the audit.

## Release and deployment evidence

- PR #36 merged at `eb3da8b1663af352a6386fef1d170d7e36784db7`.
- Auto Release run `32826544637` passed CI, both image builds, tag
  resolution, embedded-version checks, and tag/release publication.
- GitHub release tag: `v1.9.0`; registry image tags are the bare versions
  `1.9.0` and `1.9` (the registry does not publish a `v1.9.0` image tag).
- Live UI image: `ghcr.io/assetforgeai-tech/cashpilot@sha256:9fb1593d7bcd6378d0ab97be96afd598112ac13826983867a422b8750592d717`.
  The container reports `CASHPILOT_VERSION=1.9.0` and is healthy with restart
  count `0`.
- UI was recreated with `--no-deps cashpilot-ui` using the existing volumes,
  network, port, environment, security options, and restart policy. A backup
  of the previous override was retained on the VPS for rollback.
- `cashpilot-worker` remained container `60b180133540`, image
  `cashpilot-worker-local:proxy-egress`, start time
  `2026-08-20T09:04:41Z`, restart count `0`, and healthy. It was not pulled,
  recreated, restarted, or redeployed.
- The live database reported `PRAGMA integrity_check = ok`.

## UI read-only verification

Authenticated browser checks read the live `/proxy-pool` page without invoking
an action control:

- Desktop viewport: `1280px`; document width `1272px` (no horizontal overflow).
- Mobile viewport: `375px`; document width `367px` (no horizontal overflow).
- `#pool-import-protocol` is visible, labeled `Protocol`, defaults to `auto`,
  exposes exactly `Auto`, `HTTP`, and `SOCKS5`, and has a `44px` control height.
- The helper text states that Auto detects SOCKS5 or HTTP during the first
  check. Changing the selector was not used to submit a request.
- The live page title is `Proxy pool - CashPilot`; the screenshot and DOM both
  show the control in the existing Proxy Pool design system.

## Full read-only inventory sweep

The authenticated paginated API was read page-by-page with a maximum page size
of `100`. No credentials or raw endpoint values were emitted into this report.

| Check | Result |
| --- | ---: |
| Reported inventory | 1,004 |
| Pages fetched | 11 |
| Rows fetched | 1,004 |
| Stable total across pages | yes |
| Unique row IDs | 1,004 |
| Duplicate row IDs | 0 |
| Alive / dead | 1,003 / 1 |
| Protocol | HTTP: 1,004 |
| Provider | zlproxy: 1,004 |
| Active worker/instance bindings | 0 |
| Scheduler | disabled; interval 60 minutes; concurrency 32 |

### Metadata and evidence quality

- Country code, country name, and visible location are blank for all `1,004`
  rows.
- IP type is `unknown` for all `1,004` rows; all geo and IP-type timestamps
  are missing.
- Generic `last_checked_at` exists for all `1,004` rows and all are less than
  24 hours old at capture time (`2026-08-25T08:48:55Z`).
- EarnApp evidence is present for `884` rows: `306 eligible` (`CID_SET`) and
  `578 blocked` (`BLACKLIST`). `120` rows have no EarnApp verdict/evidence.
- EarnApp evidence timestamps for the `884` checked rows are less than 24
  hours old; the remaining `120` are missing rather than stale.

### Duplicate egress

- `164` rows are marked as duplicate egress, forming `145` egress groups with
  more than one row.
- The largest observed groups contain `4` rows.
- Every marked duplicate row has a canonical proxy ID (`0` missing canonical
  IDs). No active assignment or scoped lease was found in the read model.

## Root-cause evidence for missing metadata

This audit does not apply a fix. It records the evidence needed for the next
bounded task:

1. The current import batch was recorded at approximately `07:12 UTC`; generic
   probe evidence ran between `07:15` and `07:35 UTC`, while no geo or IP-type
   fields were persisted afterward.
2. The UI log window contained no intelligence/enrichment error messages, so
   the audit cannot distinguish an untriggered enrichment stage from a fully
   rate-limited/empty lookup result using logs alone.
3. A direct, single-IP invocation of the shipped lookup code returned valid
   country/type data through the regional `ipapi.is` fallback. The primary
   `ipwho.is` request returned HTTP `429`, and the primary `api.ipapi.is`
   endpoint was unreachable in that probe. This proves the fallback path can
   work, but does not justify a bulk live retry without a rate limit and
   observability plan.

## Recommended next bounded work

1. Add a read-only/preview metadata-enrichment job with explicit rate limits,
   cache-hit/miss counters, source status, retry-after handling, and a one-IP
   canary. Only after the canary proves persistence should it process the
   remaining egress IPs in bounded batches.
2. Run a separate EarnApp recheck for the `120` rows with no evidence; keep
   generic liveness and duplicate reconciliation separate from that operation.
3. Treat `VN`/`Viet Nam` canonicalization as a separate approved read-model
   change. Do not combine it with metadata refresh or EarnApp probing.

These recommendations do not authorize any live mutation. The next execution
must receive an explicit scope and retain the protected provider/lease/worker
boundaries.
