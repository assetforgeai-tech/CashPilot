# CashPilot Active Context

Updated: 2026-08-24 (NKN shared ChainDB cache canary closeout)

## Current repository state

- Canonical source branch: `main` at merge commit `ce93239`. The original
  direct-runtime and Docker canary history is retained for traceability. The LXD
  runtime landed through PR #17, guarded canary adoption through PR #18, the
  adoption timeout fix through PR #19, and the optional ChainDB acceleration
  through PRs #21-#23.
- Release `v1.6.1` is published and verified. PR #21 added the snapshot
  publisher/consumer contract, PR #22 fixed the release image build context, and
  PR #23 added publisher compatibility with the VPS's Python 3.10 runtime.
- PR #1 (Grass retirement), PR #2 (fork GHCR images), PR #3 (fork install
  surfaces), PR #4 (redacted historical evidence), PR #5 (current context),
  PR #6 (read-only baseline refresh), PR #7 (proxy worker ACK rotation), PR #8
  (post-merge baseline), PR #9 (`v1.2.0` canary context), PR #10 (NKN direct
  runtime), PRs #11-#13 (NKN canary fixes), PRs #14-#16 (NKN context history),
  PRs #17-#19 (LXD runtime, adoption and timeout fix), and PRs #21-#23 (ChainDB
  acceleration and release/runtime fixes) are merged.
- Both fork GHCR images were built and verified by the `v1.6.1` Auto Release
  workflow. The earlier deployed UI/worker evidence remains recorded in the NKN
  runtime closeout below; the dedicated publisher deployment does not authorize
  a bulk server or worker redeploy.
- The source branch remains `main`; release/deploy state is operational
  evidence and does not change the protected provider catalog.
- Proxy lease rotation is server-authoritative with worker-local probe/ACK,
  persistent sidecar configuration and fail-closed CAS semantics. Generic proxy
  assignment remains worker-level; NKN has its own direct public-IP slot model.
- Grass remains retired from the product. `test-sing` was explicitly approved
  as disposable test state and cleaned before the NKN canary; its current state
  is the worker, one LXD NKN node, and the stopped legacy Docker NKN container
  retained only for rollback evidence.
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
- New NKN slots run in an NKN-only LXD instance with the official Docker node
  inside it. Server Settings are authoritative for future creation/adoption:
  `nkn_lxd_cpu=1` and `nkn_lxd_memory_mib=1024` are the current verified values;
  saving different values never silently resizes a running node.
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
- Current source status: PRs #17-#19 and release `v1.5.1` are green. The patch
  keeps normal deploy timeout at 60 seconds and gives only guarded LXD adoption
  900 seconds. The fresh full suite passed `1515 passed, 7 skipped`. Runtime,
  heartbeat, Fleet, wallet, RPC and lease-guard snapshots keep NKN
  `PROTECTED_DONE`.

## v1.6.1 NKN ChainDB snapshot closeout (2026-08-24)

- The optional private-R2 publisher/restore path is merged through PRs #21-#23,
  released as `v1.6.1`, and deployed only to the dedicated NKN publisher VPS.
  The archive contract contains `ChainDB/` only; wallet, password, config,
  `ChainDB.config`, node identity and lease material remain outside the archive.
- A controlled cold snapshot from `test-sing` produced the manual seed object
  `cashpilot-nkn-chaindb/manual/test-sing-20260824T043345Z.tar.zst` with
  `5,783,795,401` bytes and SHA-256
  `d70d8ae06cf67266e06702894ceafd31190352f238bc6b1b77e86c4c3af14928`.
  Restoring that `ChainDB/` into the stopped publisher node preserved the
  publisher wallet/config hashes and Node ID, and both nodes returned to
  `PERSIST_FINISHED`.
- The first canonical publisher run completed successfully from block height
  `9689115`. It published
  `cashpilot-nkn-chaindb/snapshots/9689115-20260824T054653Z-9c8d29068fd741dab315d17d3c9f3fcdcfe0c389a29fefede7ba06cfd18e10e5.tar.zst`
  and then `cashpilot-nkn-chaindb/manifests/latest.json`. The archive is
  `5,795,325,602` bytes with SHA-256
  `9c8d29068fd741dab315d17d3c9f3fcdcfe0c389a29fefede7ba06cfd18e10e5`.
- Verification streamed the complete canonical object back from R2 without a
  local copy; byte count and SHA-256 matched `latest.json` and object metadata,
  and no multipart upload remained unfinished. The publisher removed its local
  archive after publication.
- Publisher container ID
  `c13a32936b8f698309a07ddb428b06fdfcae0e575da8ad89b33a71773795dffe`
  and Node ID
  `38a798d0f7de12b7064eddae9befee319e69c1b013799cdbcf954d1353cb935a`
  remained unchanged with restart count `0`. Fresh RPC evidence returned
  `PERSIST_FINISHED` at height `9689178`; identity/config hashes matched the
  pre-run baseline.
- `cashpilot-nkn-chaindb-publisher.timer` is enabled and `active (waiting)`.
  Its first verified next trigger was `2026-08-25 00:08:11 UTC`; enabling it did
  not immediately launch a second snapshot. The manual seed object lives outside
  the automated `snapshots/` retention scope and is not referenced by
  `latest.json`.
- The approved consumer optimization is implemented in the NKN host helper only:
  one verified archive per digest is cached under
  `/var/lib/cashpilot/nkn-chaindb-cache`, protected by a lock and `.partial` to
  final atomic rename, then exposed to each LXD node through a read-only disk
  device. The restore staging/atomic swap contract and publisher are unchanged;
  each node still owns a separate live `ChainDB`.
- The isolated shared-cache canary completed on `test-us` worker `3098`, slot
  `ipv4-001`, public IP `104.211.53.252`, using the existing exclusive wallet
  lease (`wallet_id=3`, assignment version `1`). The cache populated the canonical
  `5,795,325,602` byte archive once, retained SHA-256
  `9c8d29068fd741dab315d17d3c9f3fcdcfe0c389a29fefede7ba06cfd18e10e5`,
  and exposed it to the LXD instance through the read-only
  `nkn-chaindb-cache` disk device.
- A failed first restore exercised the unchanged atomic rollback path after the
  LXD stub resolver stopped responding under the cold-restore I/O load. The node
  returned to its previous `ChainDB`; the wallet, config and lease were unchanged.
  The inner official Docker runtime now receives explicit public DNS servers so
  it does not inherit a dead LXD `127.0.0.53` stub. The second restore reused the
  same cache archive without a network download: inode `325123`, size and mtime
  were unchanged and no `.partial` file remained.
- The successful second restore swapped only `ChainDB/`, preserved wallet hash
  `035cfdd43ee4c6bbf5f0d460b7eb5b8f3985ca05e1ee5bab2c36043dc6e076ca`,
  config hash
  `f75113b8edcf4c4382968c2fac963b3b1f86bb72fc1234c584c921b407b4c965`
  and Node ID
  `c36ecaa9abdcec725d889ec222834f5a1705065ede7f5857cfb56f1d5ee293d7`.
  Fresh RPC reached `PERSIST_FINISHED` above height `9689780`; worker heartbeat
  and Fleet report this node online. Publisher and `test-sing` were not changed.
- A controlled restart of only the `test-us` NKN LXD instance then proved
  `boot.autostart`, inner `restart: always`, DNS recovery, route/SNAT recovery and
  shared-cache persistence. The node returned to `PERSIST_FINISHED` at height
  `9689812` with the same Node ID, wallet/config hashes and cache inode; observed
  egress remained `104.211.53.252`.
- This shared-cache/DNS follow-up is still local to branch
  `fix/nkn-chaindb-python310` pending commit, PR, CI, merge and release. No server,
  publisher, `test-sing` or bulk worker redeploy is authorized by this evidence.

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

This section is historical Docker-canary evidence. The current runtime is the
LXD closeout recorded in the next section; the legacy Docker container remains
stopped and must not be mistaken for the active node.

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

## v1.5.1 NKN LXD closeout (2026-08-23)

- PR #17 introduced the restricted NKN host helper and LXD runtime; PR #18
  adopted the pre-provisioned canary without changing its NKN data, wallet or
  Node ID. PR #19 fixed the server timeout mismatch discovered during adoption:
  ordinary deploy remains 60 seconds and guarded adoption receives 900 seconds.
- Auto Release run `32631080399` published and verified both `v1.5.1` images.
  Only the server UI was redeployed because the fix is in `app/main.py`. The UI
  is healthy at
  `ghcr.io/assetforgeai-tech/cashpilot@sha256:08c69e606a9fdca18edb1479e9b229e04c8d2f6915d0d3779cb028c806cd4bf5`;
  SQLite integrity is `ok` and schema version remains `17`. Server snapshot:
  `/opt/cashpilot/backups/ui-20260823T163408Z`.
- `test-sing` worker `43406` remains healthy on `v1.5.0` at digest
  `sha256:35d9b31458edb306e2b98bb1583ef04bfe54592c582bdb656f71fcf0f1841247`;
  it was not recreated for the UI-only patch. The NKN LXD helper socket is
  active and restricted to `root:docker` mode `0660`.
- Active target `cashpilot-nkn-ipv4-001` has LXD IP `10.252.0.2`, hard
  `1 CPU / 1 GiB` limits and swap disabled. Its inner container
  `cashpilot-nkn` keeps ID
  `c4b7c9f3df9ec439ba1ecd636d0937ec1f1020901dc4ddba2810d147ddc73fd1`,
  `restart=always`, host networking and the official pinned image digest
  `nknorg/nkn@sha256:9a96013030545d71bdacee29922bb412a01bb71325ce246c36fb13623dfed07a`.
- Node ID is
  `2c58f11ddb37bd4c8e1bf16804bf19bd719038340afee0ea8ab373eed13604c2`;
  RPC returned `PERSIST_FINISHED` after adoption and again after the controlled
  lease-guard test. Fleet reports NKN `total=1`, `online=1`, `offline=0`.
- Wallet `1` remains `LEASED` to worker `43406`, slot `ipv4-001`, client
  `a38e77d55a2442af8fd79f096d0f69da:nkn:ipv4-001`, assignment version `3`.
  The controlled guard test forced a stale local ACK, suspended the LXD node,
  then used the authenticated server heartbeat ACK with the exact CAS tuple to
  resume it. No wallet release, reassignment, identity rotation or volume
  deletion occurred.
- Legacy Docker container
  `4a84d3d96b14468d9e6396c3e84d1352042ea5adfd955768397dd35c6283f84e`
  remains `exited` with restart policy `no`; it was not started or recreated.

## Protected provider matrix

`PROTECTED_DONE`: `earnfm`, `iproyal`, `mysterium`, `packetstream`,
`proxies-sx`, `proxybase`, `proxybase-xyz`, `proxyrack`, `repocket`, `spide`,
`traffmonetizer`, `uprock`, `urnetwork`, `wipter`, `nkn`.

No current provider is open for redesign in this branch. Any future
shared-module change requires an impact map, regression coverage, isolated
canary and explicit user approval.

## Verification status

- PR #23's fresh source suite passed `1618 passed, 2 skipped`; its release gate,
  Ruff, Tests, CodeQL, Catalog Check and Auto Release jobs all completed
  successfully.
- PR #19 passed Analyze, CodeQL, Ruff and Tests. Merge commit `7df2fdd`
  triggered Auto Release run `32631080399`; both `v1.5.1` image manifests and
  embedded versions were verified before the tag and GitHub Release were
  published.
- Fresh live evidence proves the LXD runtime, exact CAS lease-guard
  suspend/resume, UI-only upgrade isolation, Fleet `1/1/0`, wallet continuity,
  Node ID continuity and legacy Docker stopped state.
- Fresh publisher evidence proves the cold stop/archive/start sequence, full R2
  stream checksum, immutable archive plus manifest-last publication, local
  cleanup, preserved publisher identity and a daily timer in waiting state.
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
- Live/VPS verification for the historical `v1.2.0` proxy canary, historical
  `v1.3.2` Docker NKN canary and current `v1.5.1` LXD closeout is complete.
  Final NKN API proof shows worker `43406` online, Fleet NKN `1/1/0`, exclusive
  wallet assignment version `3` and redacted `PERSIST_FINISHED` evidence.
- Future provider deployment still requires an impact map and explicit approval;
  this canary did not authorize bulk redeploy, wallet rotation, credential
  rotation or changes to any protected provider.
