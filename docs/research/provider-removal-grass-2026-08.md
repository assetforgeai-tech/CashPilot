# Provider removal decision: Grass

Updated: 2026-08-21

## Decision

Grass is removed from the current CashPilot product catalog and runtime. The
repository no longer deploys, collects, imports, documents, or exposes Grass as
an active provider. This is a product decision, not a claim that historical
runtime data never existed.

The remaining catalog baseline is 14 providers:

`earnfm`, `iproyal`, `mysterium`, `packetstream`, `proxies-sx`, `proxybase`,
`proxybase-xyz`, `proxyrack`, `repocket`, `spide`, `traffmonetizer`, `uprock`,
`urnetwork`, and `wipter`.

## Safety boundaries

- The 14 remaining provider YAML files are protected; their content hashes are
  checked before release.
- No VPS, live container, provider volume, proxy lease, wallet lease, database
  migration, credential rotation, or cleanup is part of this change.
- Existing SQLite rows are not deleted or migrated. Current API views filter
  the explicit retired-provider deny-list, while raw history remains
  recoverable for audit/export. Unknown or integration-only slugs are not
  hidden merely because they are absent from the catalog.
- Legacy `store_wynd_*` keys remain in `app/database.py` so old secrets stay
  encrypted and masked. Keeping these names is compatibility handling, not
  support for a Grass deployment.
- Git history and historical changelogs are retained. They are not runtime
  documentation and must not be used as deployment instructions.

## Removed surfaces

- Service catalog entry and Docker definition.
- Collector registry, collector module, provider automation and installer
  branches.
- Dashboard/importer provider mapping and Grass-only deploy/runtime tests.
- Current earnings, payout, health, fleet, alert and worker views for retired
  provider slugs.
- Runtime-asset admin/worker access and payout confirm/reject mutation paths for
  retired provider slugs.
- Prometheus operational gauges and labels for retired provider rows, containers,
  deployments and health scores.
- Generated README service tables and documentation navigation entry.

## Compatibility behavior

Legacy records remain readable through database-level APIs for audit purposes,
but are excluded from current product aggregates, daily charts, payout alerts,
health checks, Fleet provider entries and collection-run detection. Legacy
secret keys are never returned in plaintext by the masked settings endpoint.
Runtime-asset endpoints hide legacy Grass rows and return not-found for Grass
read/write requests; payout mutations likewise refuse to alter retired rows.
The retired-provider predicate is case-insensitive and trims outer whitespace.

The generic raw worker command contract is unchanged. It remains a low-level
worker transport and is intentionally not converted into a catalog-only API by
this removal.

## Verification evidence

- Catalog: exactly 14 active provider slugs; 12 bandwidth and 2 DePIN.
- Collector registry: 8 current collectors.
- Docker images: 13 catalog entries with images; the manual-only catalog entry
  remains deploy-surface aware.
- Full regression suite: 1281 passed, 7 skipped (`python -m pytest -q`).
- Legacy aggregate, health, alert and masked-secret regressions cover the
  retired-provider boundary, including metrics, runtime assets, payout
  mutations and case normalization.
- Ruff lint/format, JavaScript checks, catalog/docs generators and strict docs
  build pass. Docker smoke builds remain unrun because Docker is unavailable on
  the analysis machine.
- No provider YAML outside the removed definition is changed.

## Future changes

Reintroducing this provider would require a new product decision, a fresh
catalog/runtime contract, isolated tests, an impact map for shared code, and
explicit approval. Historical login experiments, dashboard observations, or
upstream changes are not authorization to restore it.
