# NKN HTTP-detail rollout

## Change

- Server release `v1.53.11` includes bounded, newline-normalized HTTP error
  details for NKN slot deployment failures.
- Non-HTTP exceptions remain type-only; wallet material, credentials, and URLs
  are not logged.
- PR #421 merged as `d01d7cc15464d6c7bb1c6b110b29469866cfe3ed`.

## Verification

- PR checks: Analyze, strict build, Ruff, and full test job passed.
- Server UI: `ghcr.io/assetforgeai-tech/cashpilot:1.53.11`, healthy, data volume
  preserved.
- Azure workers `118903` and `118904`: worker image `1.53.11`, healthy, worker
  identity files and data volumes preserved.

## Current finding

The next deploy cycle reports `Worker request failed` for some NKN slots while
the worker helper remains active. The stale-assignment HTTP detail is therefore
not yet observable for those failures; the worker-side request path still needs
reconciliation. NKN remains below the production gate until matching ACKs and
stable runtime state are observed.
