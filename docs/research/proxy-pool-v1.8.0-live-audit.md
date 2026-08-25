# Proxy Pool v1.8.0 Audit and v1.8.1 Closeout

Date: 2026-08-25

Scope: authenticated, read-only verification of the released Proxy Pool UI and
its read model on the CashPilot server. This audit did not import, delete,
recheck, rotate, lease, release, or assign a proxy. It did not change a worker,
provider container, wallet, credential, database row, or scheduler setting.

## Release and deployment boundary

- PR #33 is merged at `098ac2b3eee1a77b09ec7855c328485f9ce7ef0a`.
- Auto Release run `32813965539` completed successfully and published `v1.8.0`.
- PR #34 merged the isolated dashboard-session masking fix at
  `a3d2dce4bef66fdc1053fefda38cdbde3b422ed7`. Auto Release run `32817037347`
  completed successfully and published `v1.8.1`.
- The live UI reports `CASHPILOT_VERSION=1.8.1`, uses the verified UI digest
  `sha256:3ba1e9b4ba1cfb7e24eb9e8df47257953d4474f2dcdc29799c3a40ebeb22244d`,
  and is Docker-healthy with restart count `0`. Its container ID begins
  `0e67b499ff69`.
- The UI-only override is
  `/opt/cashpilot/docker-compose.ui-v1.8.1.override.yml`, SHA-256
  `fab6b15055a05a682a0571da8830d2f607767f34cc4c03b9e1d92cc0b830da25`.
- `cashpilot-worker` remained container `60b180133540` on
  `cashpilot-worker-local:proxy-egress`, start time
  `2026-08-20T09:04:41.088040401Z`, restart count `0`, and healthy. No worker
  pull, restart, recreate or redeploy was used.
- The fresh post-release read-only check reports schema `18` and DB integrity
  `ok`.

## Full inventory sweep

The closeout sweep paged through all `3,223` rows using
`GET /api/proxy-pool/page`. It retrieved `33` pages, with a maximum of `100`
items and `117,744` bytes in any response. No credential fields were returned
by the endpoint.

| Measure | Live count |
| --- | ---: |
| Inventory | 3,223 |
| Generic alive | 1,844 |
| Generic dead/failed | 1,379 |
| Egress known | 1,844 |
| Egress unresolved | 1,379 |
| Country known | 1,831 |
| IP type known | 1,020 |
| Metadata pending aggregate | 824 |
| Duplicate egress rows | 755 |
| Canonical available / generic usable | 1,089 |
| EarnApp eligible | 922 |
| EarnApp leaseable | 338 |
| EarnApp checked | 1,793 |
| EarnApp not checked | 51 |
| EarnApp skipped because generic check failed | 1,379 |
| Active legacy leases | 0 |
| Active scoped leases | 0 |

Scheduler state is enabled with a `60` minute interval and concurrency `64`.

### Label and metadata observations

- Country values contain both `VN` and `Viet Nam` (`39` and `1,542` rows), so
  the current filter/export surface has two labels for the same country. This
  is a normalization gap, not evidence that the proxies are in different
  countries.
- The same sweep reports `US` on `250` rows. It does not invent a country for
  failed or unresolved egress.
- `1,379` rows have no authoritative egress because the generic probe failed;
  their UI location and IP type correctly render as failed/unresolved rather
  than inventing metadata.
- `13` rows render location as `Metadata pending`; the aggregate pending count
  is `824` because it includes rows missing either location or IP type. The
  audit did not trigger a bulk enrichment run.
- EarnApp evidence is checked for `1,793` rows, not checked for `51`, and
  skipped for the `1,379` generic failures. The closeout did not infer freshness
  from historical evidence or trigger a re-probe.

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
changes.

The authenticated `v1.8.1` proof closes the contract: the ordinary `/api/config`
map does not contain `dawn_dashboard_session`, while
`_secrets.dawn_dashboard_session` is `true`. The value was not printed, copied
to docs, rotated or deleted. The internal runtime read path remains covered by
the regression test added in PR #34.

## Protected-state confirmation

- No proxy import, delete, recheck, duplicate export, lease, release, or
  scheduler write occurred.
- No provider container, identity, volume, wallet, credential, worker, or active
  lease was changed.
- MYST and NKN direct-only baselines remain outside this audit's write scope.
- Grass remains retired and was not reintroduced.

## Follow-up candidates (not executed)

1. Prepare a read-only impact map for canonical country-label normalization
   (`VN` versus `Viet Nam`) and bounded metadata refresh.
2. Design a scoped, freshness-aware EarnApp evidence re-probe; do not bulk
   recheck or revoke existing state as part of that design step.
3. Consider server-side pagination for the MYST/NKN owner inventory endpoints
   as a separate operability improvement.
