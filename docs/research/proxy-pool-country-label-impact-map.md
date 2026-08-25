# Proxy Pool Country-Label Impact Map

Date: 2026-08-25

Scope: impact analysis and implemented read-model decision for the `VN` /
`Viet Nam` label split observed in the Proxy Pool `v1.8.1` live audit. This
document does not authorize or perform a database rewrite, proxy recheck,
lease change, provider change, release, or deployment. The separately approved
metadata-only canary/batch procedure is documented in
`proxy-pool-metadata-location-impact-map.md`.

## Current evidence flow

1. `app/proxy_intelligence.py` obtains country evidence through the
   source-aware, proxy-routed lookup and normalizes `country_code` to ISO
   alpha-2 while preserving the provider's `country_name` text. If only the
   quality source returns a country code, `merge_intelligence()` can produce a
   code-only location such as `VN`.
2. `app/routers/proxies.py::_refresh_exit_ip_intelligence()` caches evidence by
   authoritative egress IP and passes it to the database update path.
3. `app/database.py::update_proxy_endpoint_intelligence()` persists three
   related values: `location`, `country_code`, and `country_name`. It preserves
   raw evidence; canonicalization is applied in the read model.
4. `app/database.py::list_proxy_pool_page()` derives `display_location` from
   the ISO code first, then known country-name aliases, then an explicit
   metadata-state label. Exact location filters, sorting, distinct filter
   options, aggregate metadata counts, and server-side search all consume this
   expression.
5. `app/templates/proxy_pool.html::proxyLocationLabel()` displays a localized
   human country name from the canonical code while keeping the code and raw
   source fields in the tooltip.
6. `app/routers/proxies.py` exports `location`, `country_code`, and
   `country_name`; filtered exports route through the paginated read model, so
   the alias split also affects exact location export selection.

## Affected surfaces

| Surface | Effect of `VN` and `Viet Nam` coexisting |
| --- | --- |
| Location column | Previously split; now one localized label is derived from the ISO code. |
| Location filter | Previously split; now one canonical code option selects all known aliases. |
| Search | Raw name and code remain searchable while the visible label is normalized. |
| Sort | Rows now group by the canonical read-model code. |
| Filtered/location export | The canonical filter includes rows stored under known name aliases. |
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

## Implemented design

1. Canonicalize the read-model location key by ISO `country_code`; retain the
   original `country_name` evidence.
2. Use the same contract in page rows, filters, sorting, search and filtered
   exports. `VN`, `Viet Nam`, and `Vietnam` resolve to one filter bucket.
3. Keep `country_code` as the future EarnApp lease predicate. UI labels are
   presentation only and never participate in lease selection.
4. Use the metadata-only endpoint for repair. Do not run a bulk generic or
   EarnApp recheck solely to repair labels.
5. If persisted cleanup is ever desired, require a separate approved,
   bounded, idempotent backfill with before/after counts and rollback evidence.

## Decision for the current change

The current branch implements the read-model contract, source-aware metadata
diagnostics, and a bounded metadata-only refresh. It does not rewrite existing
country rows by itself. Live mutation is limited to the separately verified
one-proxy canary followed by bounded batches after release.
