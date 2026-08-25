# Proxy Pool v1.8.0 Live Audit

Date: 2026-08-25

Scope: authenticated, read-only verification of the released Proxy Pool UI and
its read model on the CashPilot server. This audit did not import, delete,
recheck, rotate, lease, release, or assign a proxy. It did not change a worker,
provider container, wallet, credential, database row, or scheduler setting.

## Release and deployment boundary

- PR #33 is merged at `098ac2b3eee1a77b09ec7855c328485f9ce7ef0a`.
- Auto Release run `32813965539` completed successfully and published `v1.8.0`.
- `origin/main` is `76f740e1c7fd1920cae887d6af5ead60f48ff357` (the release compose-pin follow-up).
- The live UI reports `CASHPILOT_VERSION=1.8.0`, uses the verified UI digest
  `sha256:3b2ab3c4217e35dc0223d72ace025f8fac26f37eef42ba851f517df4e00ccb62`,
  and is Docker-healthy with restart count `0`.
- `cashpilot-worker` remained on its existing image/container, with its prior
  start time and restart count unchanged. No worker redeploy was used.
- Pre-deploy DB integrity was `ok`; the live post-deploy read-only check also
  reports schema `18` and integrity `ok`.

## Full inventory sweep

The authenticated sweep paged through all `3,223` rows using
`GET /api/proxy-pool/page`. It retrieved `33` pages, with a maximum of `100`
items and `117,918` bytes in any response. No credential fields were returned
by the endpoint.

| Measure | Live count |
| --- | ---: |
| Inventory | 3,223 |
| Generic alive | 1,932 |
| Generic dead/failed | 1,291 |
| Egress known | 1,932 |
| Egress unresolved | 1,291 |
| Country known | 1,922 |
| IP type known | 1,109 |
| Metadata pending | 823 |
| Duplicate egress rows | 844 |
| Canonical available / generic usable | 1,088 |
| EarnApp eligible | 924 |
| EarnApp leaseable | 337 |
| EarnApp blocked | 661 |
| EarnApp quality-rejected | 209 |
| EarnApp not checked | 138 |
| EarnApp skipped because generic check failed | 1,291 |
| Active legacy leases | 0 |
| Active scoped leases | 0 |

Scheduler state is enabled with a `60` minute interval and concurrency `64`.

### Label and metadata observations

- Country values contain both `VN` and `Viet Nam` (`40` and `1,632` rows), so
  the current filter/export surface has two labels for the same country. This
  is a normalization gap, not evidence that the proxies are in different
  countries.
- `1,291` rows have no authoritative egress because the generic probe failed;
  their UI location and IP type correctly render as failed/unresolved rather
  than inventing metadata.
- `823` rows still have pending location or IP-type metadata. The audit did not
  trigger a bulk enrichment run.
- The current latest EarnApp evidence is stale for `1,429` rows when compared
  with the current egress. Stale evidence is not treated as lease authority;
  no leases were created or revoked during this audit.

## UI verification

Authenticated Playwright checks passed at `1440px` desktop and `375px` mobile:

- `document.body.scrollWidth` did not exceed the viewport width.
- Initial rendering used `20` rows and a bounded `page_size=20` request.
- Search for a non-existent term produced zero rows and sent the search query
  to the server-side read model.
- Keyboard Enter on a sortable header sent an ascending request; a subsequent
  click sent a descending request. `aria-sort` matched the request direction.
- Pagination sent the next page request and rendered the next bounded page.
- Provider filter options and row counts updated through the server-side query.
- No browser console errors or page errors occurred in the authenticated run.
- The mobile table remains intentionally horizontally scrollable inside its
  table wrapper; the page itself does not overflow horizontally.

The first unauthenticated harness attempt produced external-font/CDN CORS
messages because it attached the bearer header to third-party resources. That
false negative was discarded; the authenticated same-origin run above is the
authoritative UI result.

## Authenticated endpoint map

HTML pages:

| Surface | Route | Access |
| --- | --- | --- |
| Fleet | `GET /fleet` | Any authenticated session |
| Settings | `GET /settings` | Owner session |
| MYST Wallet | `GET /myst-wallet` | Owner session |
| NKN Wallet | `GET /nkn-wallet` | Owner session |

Read/API routes verified with the owner bearer credential (the credential value
is intentionally not recorded here):

| Surface | Route | Guard | Returned material |
| --- | --- | --- | --- |
| Fleet summary | `GET /api/fleet/summary` | Reader or higher | Aggregate workers/containers and redacted NKN counts |
| Fleet rows | `GET /api/workers` | Authenticated API role | Worker status, containers, provider state, redacted worker key |
| Settings | `GET /api/config` | Owner | Non-secret config plus `_secrets` presence map |
| Environment info | `GET /api/env-info` | Owner | Environment labels and secret presence only |
| MYST inventory | `GET /api/admin/myst-wallets` | Owner | Wallet metadata/lease state; no raw wallet material |
| NKN inventory | `GET /api/admin/nkn-wallets` | Owner | Wallet metadata/evidence; no wallet JSON/password |
| NKN ChainDB | `GET /api/nkn/chaindb/status` | Owner | Masked config and non-secret latest-manifest state |

Observed live response sizes were `3` workers, `6,266` MYST wallet rows and
`26,021` NKN wallet rows. These owner-only list endpoints are read-only but are
currently full-list responses; pagination is a future operability improvement,
not a reason to mutate the inventories now.

## Finding and narrowly scoped fix

The pre-fix v1.8.0 read returned a populated `dawn_dashboard_session` field in
the ordinary config map. The value was session-shaped (469 characters) and was
not represented only by the `_secrets` presence map. The value itself is not
reproduced in this report.

The fix is intentionally isolated to the `dashboard_session` secret suffix and
its regression test. The impact map is recorded in
`docs/research/proxy-pool-session-mask-impact-map.md`. No live credential was
rotated or deleted, and the patch is not bundled with proxy rechecks or provider
changes. Post-release proof is required before declaring the contract closed.

## Protected-state confirmation

- No proxy import, delete, recheck, duplicate export, lease, release, or
  scheduler write occurred.
- No provider container, identity, volume, wallet, credential, worker, or active
  lease was changed.
- MYST and NKN direct-only baselines remain outside this audit's write scope.
- Grass remains retired and was not reintroduced.

## Follow-up candidates (not executed)

1. Patch and test the exact `dawn_dashboard_session` masking gap after approval.
2. Prepare a read-only impact map for canonical country-label normalization
   (`VN` versus `Viet Nam`) and bounded metadata refresh.
3. Design a scoped, freshness-aware EarnApp evidence re-probe for the `1,429`
   stale rows; do not bulk recheck or revoke existing state as part of that
   design step.
4. Consider server-side pagination for the MYST/NKN owner inventory endpoints
   after the masking issue is closed.
