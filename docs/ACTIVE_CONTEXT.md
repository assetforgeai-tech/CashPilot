# CashPilot Active Context

Updated: 2026-08-22 (post-merge proxy ACK baseline)

## Current repository state

- Canonical branch: `main`.
- Audited product/repository baseline: `78e95538b28d51e4b09dc663873928b69dcab414`
  (`78e9553`), the squash merge commit for PR #7.
- PR #1 (Grass retirement), PR #2 (fork GHCR images), PR #3 (fork install
  surfaces), PR #4 (redacted historical evidence), PR #5 (current context),
  PR #6 (read-only baseline refresh) and PR #7 (proxy worker ACK rotation) are
  merged.
- Release `v1.1.1` remains published with both fork GHCR images and passed the
  release image verification gates.
- The merge commit deliberately contains `[skip ci]`: no new release, tag,
  GHCR image or deployment was created. The latest published release remains
  `v1.1.1`.
- Proxy lease rotation is now server-authoritative with worker-local probe/ACK,
  persistent sidecar configuration and fail-closed CAS semantics. The current
  assignment model remains worker-level; public-IP/provider slot topology is a
  follow-up and is not yet deployed.
- The removal is repository-only. This context does not authorize a deploy,
  VPS mutation, container recreation, credential rotation, proxy rotation or
  wallet operation.
- The implementation decision and safety boundaries are recorded in
  `docs/research/provider-removal-grass-2026-08.md`.

## Product baseline

- Current catalog: 14 providers, 12 bandwidth and 2 DePIN.
- Current collectors: 8.
- Current Docker-deployable catalog entries: 13; manual-only catalog behavior
  remains explicit.
- The 14 provider YAML definitions are the protected baseline. Do not change
  them incidentally while completing this branch.
- Mysterium remains direct-only. Its wallet inventory, lease, identity,
  WireGuard/TUN and runtime contracts are not altered by this branch.

## Retired-provider compatibility

- Grass is absent from catalog, runtime, collector, importer,
  dashboard and generated navigation.
- Historical SQLite earnings, payout, deployment and worker rows are not
  deleted. Current APIs filter retired slugs from product views and aggregates.
- Legacy secret-key suffixes remain encrypted/masked for compatibility; they do
  not make the retired provider deployable.
- Git history and historical changelog entries remain available for research.

## Product work represented by this merged baseline

- Removed provider YAML, collector, installer/automation paths and provider-only
  tests/fixtures.
- Added explicit retired-provider filtering for current earnings, health,
  alerts, Fleet and worker views without mutating stored legacy rows. Unknown
  or test-only slugs are not treated as retired merely because they are absent
  from the catalog.
- Added the same explicit boundary to Prometheus refresh gauges and lifecycle /
  collection metric labels, so legacy Grass rows do not leak through `/metrics`.
- Added the same boundary to runtime-asset admin/worker endpoints and payout
  confirm/reject mutations; legacy rows remain auditable but cannot be used as
  current Grass operations.
- Centralized the retired-provider predicate and made it case-insensitive, so
  `grass`, `Grass` and padded variants follow the same boundary across API,
  worker heartbeat, metrics and database aggregates.
- Preserved the generic raw worker command contract; official catalog deploy
  routes naturally return not-found for the retired slug.
- Removed the retired provider from the Chrome importer and regenerated README
  tables/documentation navigation.
- Added regression tests for masked legacy secrets, hidden legacy rows,
  aggregate/chart exclusion, health-check exclusion, collection-run detection
  and official deploy rejection.
- Moved the old local Grass lab/profile artifacts to the non-Git quarantine
  `secret/retired/grass-20260821`; external repositories were not touched.

## Proxy ACK rotation baseline

- The server remains the only proxy-pool and lease authority. A candidate is
  not committed until the worker probes it from the VPS, stages it into the
  named sing-box sidecar volume, restarts only the affected sidecars and returns
  a redacted binding ACK.
- Failed probe/apply/ACK/CAS or ambiguous transport leaves the previous lease
  intact; token-checked runtime rollback is best effort only when the worker may
  have applied a candidate.
- The worker probe endpoint accepts only the built-in safe target set. Arbitrary
  request-supplied URLs are rejected before network access to prevent SSRF.
- No live worker, proxy lease, provider identity, volume or database was touched
  while implementing or merging this baseline.

## Protected provider matrix

`PROTECTED_DONE`: `earnfm`, `iproyal`, `mysterium`, `packetstream`,
`proxies-sx`, `proxybase`, `proxybase-xyz`, `proxyrack`, `repocket`, `spide`,
`traffmonetizer`, `uprock`, `urnetwork`, `wipter`.

No provider is open for redesign in this branch. Any future shared-module change
requires an impact map, regression coverage, isolated canary and explicit user
approval.

## Verification status

- Full suite for the merged ACK branch: 1358 passed, 7 skipped
  (`python -m pytest -q`), including proxy rotation, redaction and SSRF
  regression coverage.
- PR #7 CI passed `CodeQL`, `Analyze`, `build (strict)`, `ruff` and `test`;
  deploy was skipped by policy. The merge commit has no post-merge workflow run.
- Ruff lint and browser-free behavior checks pass; README/catalog and
  documentation-nav checks pass.
- `mkdocs build --strict` passes with a temporary docs-only environment. The
  build reports the internal research/onboarding pages as intentionally
  unlisted from the public nav.
- Docker smoke builds were not run because Docker CLI/daemon is unavailable on
  this Windows machine. No dependency, lockfile, or VPS workaround was used.
- `git diff --check` passes, and all 14 protected provider YAML hashes match
  the merged baseline. The read-only baseline audit also validated graph coverage for 301/301
  scanned files and refreshed the local knowledge/domain graph artifacts.
- No live or VPS verification was performed as part of the repository cleanup.
- Release-readiness and VPS canary remain separate, explicitly gated follow-up
  steps; neither is authorized by this context update.
