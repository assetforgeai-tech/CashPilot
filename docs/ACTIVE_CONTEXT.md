# CashPilot Active Context

Updated: 2026-08-23 (NKN live canary complete; docs-only closeout)

## Current repository state

- Canonical source branch: `main` at
  `4c55eac762dc375d1381cab42a902ec21796793f` (`4c55eac`). The live-canary
  evidence is being recorded on docs-only branch `docs/nkn-live-canary`.
- NKN direct runtime merged through PR #10. Bootstrap reuse, assignment-CAS
  removal and light-node memory bounds merged through PRs #11-#13.
- PR #1 (Grass retirement), PR #2 (fork GHCR images), PR #3 (fork install
  surfaces), PR #4 (redacted historical evidence), PR #5 (current context),
  PR #6 (read-only baseline refresh), PR #7 (proxy worker ACK rotation), PR #8
  (post-merge baseline), PR #9 (`v1.2.0` canary context), PR #10 (NKN direct
  runtime), and PRs #11-#13 (NKN canary fixes) are merged.
- Release `v1.3.2` is published with both fork GHCR images and passed the
  release image verification gates. The exact deployed image digests are
  recorded below.
- The source branch remains `main`; release/deploy state is operational
  evidence and does not change the protected provider catalog.
- Proxy lease rotation is server-authoritative with worker-local probe/ACK,
  persistent sidecar configuration and fail-closed CAS semantics. Generic proxy
  assignment remains worker-level; NKN has its own direct public-IP slot model.
- Grass remains retired from the product. `test-sing` was explicitly approved
  as disposable test state and cleaned before the NKN canary; it now contains
  only the worker and the isolated NKN node.
- The implementation decision and safety boundaries are recorded in
  `docs/research/provider-removal-grass-2026-08.md`.

## Product baseline

- Current catalog: 15 providers, 13 bandwidth and 2 DePIN.
- Current collectors: 9 (NKN beneficiary balance plus node summary).
- Current Docker-deployable catalog entries: 14; manual-only catalog behavior
  remains explicit.
- The 14 pre-existing provider YAML definitions remain the protected baseline.
  NKN is now also `PROTECTED_DONE` after its isolated direct-only canary; no
  current provider is open for incidental redesign.
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

## NKN implementation status

- NKN is official `nknorg/nkn:latest`, direct-only, and uses one exclusive
  wallet lease per bootstrap-discovered public IPv4 slot.
- Host bootstrap owns public-IP discovery, bridge/SNAT routing, Docker
  prerequisites and persistent `LimitNOFILE=1048576`; worker deploy only reads
  the resulting slot state and never mutates host routes.
- Server auto-deploy leases and deploys slots sequentially. A failed slot keeps
  its lease for retry; deliberate remove is the only normal release path.
- Worker heartbeat reports redacted `getnodestate` evidence; `PERSIST_FINISHED`
  plus a running container is required for online status. NKN balance uses the
  official wallet RPC and the Settings beneficiary address.
- Pre-PR audit closed the fleet-wide slot-id collision, generic deploy bypass,
  fake global deployment row, public-IP rebinding, stale evidence, Docker client
  lifecycle, zero-slot completion and worker slot-state mount gaps. Reclaimed
  assignment tokens are now lease-guarded end to end. The worker suspends an
  unacknowledged node at 14 minutes without deleting identity, ahead of the
  server's 15-minute reclaim; a valid ACK resumes it, while a rejected stale
  token removes only its label-matched NKN container/volume.
- Current source status: PR #13 and release `v1.3.2` are green; the fresh full
  docs-branch suite passed `1456 passed, 7 skipped`. The
  unchanged `test-sing` canary completed first sync, and fresh runtime,
  heartbeat, Fleet, wallet and collector snapshots close NKN as
  `PROTECTED_DONE`.

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
- Before the live canary, no live worker, proxy lease, provider identity, volume
  or database was touched while implementing or merging this baseline.

## v1.2.0 live canary (2026-08-22)

- VPS server UI was upgraded alone to
  `ghcr.io/assetforgeai-tech/cashpilot:1.2.0` at digest
  `sha256:4517ad2110bbaea5caaa5ab7ffdde82a5294163f852a35f97695e247ae74238b`.
  It is healthy; SQLite integrity is `ok` and schema version is `17`.
- VPS test-sing worker `34253` was upgraded alone to
  `ghcr.io/assetforgeai-tech/cashpilot-worker:1.2.0` at digest
  `sha256:e731983774bfe5035bf7ca40e53fbeade47913826f00d33bf99d2b4b75e580a5`.
  Heartbeat is `online`, key confirmation remains true and the worker reports
  `1.2.0`.
- The test-sing worker's `/data/.worker_id` and `/data/.worker_key` hashes are
  unchanged. All 32 non-worker provider containers retained their IDs,
  restart counts and runtime state; MYST direct was not recreated.
- An isolated sidecar canary used proxy pool endpoint `5802` only. It passed
  worker-local probe, apply, redacted ACK, finalize/rollback and finalize/
  confirm paths. The worker assignment and proxy lease remained unchanged;
  the canary container and volume were removed afterward.
- Proxy Pool scheduler was restored to its pre-canary policy:
  `enabled=true`, interval `60` minutes, concurrency `64`.
- Test-sing systemd now has a separate v1.2.0 override/drop-in so a future
  service restart does not silently fall back to the old image. The original
  three untracked compose files remain untouched.
- Protected backups and checksums:
  server `/opt/cashpilot/backups/v1.2.0-canary-20260822T072108Z`;
  test-sing `/home/kalinh/cashpilot-backups/v1.2.0-worker-canary-20260822T072741Z`.
  These paths contain operational backup/evidence files; credentials were not
  printed or added to Git.
- The server-local custom worker remains `cashpilot-worker-local:proxy-egress`
  (`dev`) by design; it was not bulk-redeployed. This is an explicit mixed
  deployment state, not evidence that the release failed.

## v1.3.2 NKN live canary (2026-08-22/23)

- Auto Release for commit `4c55eac` published and verified both `v1.3.2`
  images. The server UI runs
  `ghcr.io/assetforgeai-tech/cashpilot@sha256:25450f4790a98f53508228e726f2e3ee1f8701e024c852acfe3a841fd302f31e`;
  `test-sing` worker `43406` runs
  `ghcr.io/assetforgeai-tech/cashpilot-worker@sha256:e487e8acaf56043df18c906ce16e961e3e86a6ac27b9420429d055c1b8a87a28`
  and reports version `1.3.2`.
- The approved clean `test-sing` canary has one direct slot at public IP
  `4.193.231.232`, bridge `cashpilot-direct-ipv4-001`, and only two containers:
  `cashpilot-worker` plus `nkn-direct-ipv4-001`.
- NKN container ID
  `4a84d3d96b14468d9e6396c3e84d1352042ea5adfd955768397dd35c6283f84e`
  has remained stable through the VPS reboot. It uses the official
  `nknorg/nkn:latest` image, private volume `cashpilot-nkn-ipv4-001-data`,
  one CPU, 1 GiB RAM, PIDs limit 512, `restart: always`, and TCP/UDP ports
  `30000-30005` bound to the slot private IP.
- Wallet `1` remains exclusively `LEASED` to worker `43406`, slot
  `ipv4-001`, assignment version `3`; the worker state and heartbeat expose no
  wallet JSON or password. Node ID begins `2c58f11ddb37`; container restart
  count is `0` and OOM state is false.
- The authenticated NKN credential test reads the authoritative Settings
  beneficiary and reports `17006.09284572 NKN`. The unchanged node reached
  `PERSIST_FINISHED` at RPC height `9684184` and continued accepting blocks.
- Fresh heartbeats returned HTTP 200 and synchronized redacted evidence
  `{running: true, online: true, sync_state: PERSIST_FINISHED}`. Fleet reports
  `total_nodes=1`, `online=1`, `offline=0`; wallet `1` remains `LEASED` to
  worker `43406`, slot `ipv4-001`, assignment version `3`.
- After the recorded VPS reboot, no manual container restart, recreate, remove,
  wallet rotation or provider redeploy was used to obtain completion evidence.
  NKN is now `PROTECTED_DONE`; keep this successful node, identity volume and
  lease unchanged unless a separately approved lifecycle operation requires
  otherwise.

## Protected provider matrix

`PROTECTED_DONE`: `earnfm`, `iproyal`, `mysterium`, `packetstream`,
`proxies-sx`, `proxybase`, `proxybase-xyz`, `proxyrack`, `repocket`, `spide`,
`traffmonetizer`, `uprock`, `urnetwork`, `wipter`, `nkn`.

No current provider is open for redesign in this branch. Any future
shared-module change requires an impact map, regression coverage, isolated
canary and explicit user approval.

## Verification status

- Fresh full docs-branch suite: `1456 passed, 7 skipped`; targeted NKN,
  credential and docs-safety suite: `77 passed`.
- Fresh live canary evidence passed apply/rollback/confirm isolation gates;
  no database CAS row was fabricated for the isolated sidecar.
- Commit `4c55eac` passed CodeQL, Lint, Catalog Check, Tests and Auto Release;
  both `v1.3.2` image manifests and embedded versions were verified.
- Ruff lint, Python compileall and browser-free behavior checks pass;
  README/catalog and documentation-nav checks pass.
- `mkdocs build --strict` passes with a temporary docs-only environment. The
  build reports the internal research/onboarding pages as intentionally
  unlisted from the public nav.
- Docker smoke builds were not run because Docker CLI/daemon is unavailable on
  this Windows machine. No dependency, lockfile, or VPS workaround was used.
- `git diff --check` passes, and all 14 protected provider YAML hashes match
  the merged baseline. The read-only baseline audit also validated graph coverage for 301/301
  scanned files and refreshed the local knowledge/domain graph artifacts.
- `ruff format --check` continues to report only the two pre-existing baseline
  files `tests/test_ci_gates_report_what_they_checked.py` and
  `tests/test_worker_myst_sync.py`; neither file is changed by this docs branch.
- Live/VPS verification for the `v1.2.0` proxy canary and `v1.3.2` NKN canary is
  complete. Final NKN API proof shows worker `43406` online, Fleet NKN
  `1/1/0`, exclusive wallet assignment version `3` and a successful balance
  collector without exposing wallet material.
- Future provider deployment still requires an impact map and explicit approval;
  this canary did not authorize bulk redeploy, wallet rotation, credential
  rotation or changes to any protected provider.
