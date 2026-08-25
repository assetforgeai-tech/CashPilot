# Proxy Pool Country-Label Impact Map

Date: 2026-08-25

Scope: read-only analysis of the `VN` / `Viet Nam` label split observed in the
Proxy Pool `v1.8.1` live audit. This document does not authorize or perform a
database rewrite, proxy recheck, metadata refresh, lease change, provider
change, release, or deployment.

## Current evidence flow

1. `app/proxy_intelligence.py` obtains country evidence from `ipwho.is` and
   normalizes `country_code` to uppercase while preserving the provider's
   `country_name` text. If only the quality source returns a country code,
   `merge_intelligence()` can produce a code-only location such as `VN`.
2. `app/routers/proxies.py::_refresh_exit_ip_intelligence()` caches evidence by
   authoritative egress IP and passes it to the database update path.
3. `app/database.py::update_proxy_endpoint_intelligence()` persists three
   related values: `location`, `country_code`, and `country_name`. It does not
   currently canonicalize aliases.
4. `app/database.py::list_proxy_pool_page()` derives `display_location` as
   `country_name`, then `country_code`, then a metadata-state label. Exact
   location filters, sorting, distinct filter options, aggregate metadata
   counts, and server-side search all consume this expression.
5. `app/templates/proxy_pool.html::proxyLocationLabel()` uses the same visible
   priority (`country_name` before `country_code`) for each rendered row.
6. `app/routers/proxies.py` exports `location`, `country_code`, and
   `country_name`; filtered exports route through the paginated read model, so
   the alias split also affects exact location export selection.

## Affected surfaces

| Surface | Effect of `VN` and `Viet Nam` coexisting |
| --- | --- |
| Location column | The same country appears under two visible labels. |
| Location filter | Two options exist and each exact filter selects only its own label. |
| Search | Both aliases are searchable, but operators must know which form a row contains. |
| Sort | Code-only and country-name rows sort into different groups. |
| Filtered/location export | An exact export can omit rows stored under the other alias. |
| Aggregate interpretation | Country totals require grouping by `country_code`, not visible label alone. |
| Intelligence cache | A cached code-only result can preserve `VN` until a later successful country-name lookup. |

## Protected contracts not affected

Country labels are not predicates in the generic liveness check, authoritative
egress detection, duplicate-egress canonicalization, legacy worker lease,
provider-scoped lease, EarnApp `CID_SET` qualification, provider masking, proxy
rotation acknowledgement, or release/reclaim logic. A future display
normalization therefore must not modify these contracts or any protected
provider runtime.

The following state remains outside the scope of country-label work:

- active or historical proxy assignments and provider-scoped leases;
- proxy endpoint credentials and encrypted raw import evidence;
- provider catalog/runtime/collector files and worker sidecars;
- MYST/NKN wallets, identities, volumes, and direct-only behavior;
- retired Grass history;
- scheduler settings and probe freshness.

## Risks of a bulk write

A direct `UPDATE` from `VN` to `Viet Nam` would make the table look consistent,
but it would mix presentation policy with live evidence and could race with a
probe or cached refresh. It would also change exact filter/export results in
one operation and provide no compatibility period for saved operator queries.
Re-running all probes only to repair labels would create unrelated proxy and
EarnApp evidence changes. Neither action is justified by this display-quality
finding.

## Recommended future design

1. Canonicalize the visible country label in a small shared helper keyed first
   by ISO `country_code`; retain the original `country_name` evidence.
2. Use that helper consistently in the paginated read model, filter options,
   exact filter matching, UI rendering, and filtered exports.
3. Treat `VN`, `Viet Nam`, and `Vietnam` as aliases for filtering/search while
   keeping `country_code = VN` authoritative for grouping.
4. Add database/read-model and frontend regression tests before changing any
   production path.
5. If persisted cleanup is still desired, design a separately approved,
   bounded, idempotent backfill with before/after counts and rollback evidence.
6. Keep metadata refresh separate and bounded; never combine label cleanup with
   bulk generic or EarnApp rechecks.

## Decision for the current change

Do not change country-label production code or live rows. The only product
change paired with this impact map is the request-scoped Proxy Pool import
protocol selector. It does not consume or mutate location evidence.
