# CashPilot Active Context

## EarnApp macOS LAN-profile recovery (2026-09-04)

- PR #119 merged as `92eb0e1` and release `v1.19.3` completed successfully.
  The server UI and only test-US worker `3098` were upgraded to `1.19.3`;
  both are healthy. No protected provider container, iOS node, Ubuntu node,
  proxy lease, account assignment, identity volume or UUID was changed.
- The two macOS nodes were already linked to their intended accounts. Repeated
  authenticated link checks returned the exact device UUIDs, so missing link
  was not the root cause of their offline state.
- The root cause was the persisted `lan_ip=172.31.255.1`. SDK `1.660.577`
  deliberately filters the full Docker bridge range `172.16.0.0/12`, producing
  `devs changed: found 0 devs`. The profile migration changed only runtime
  metadata to `lan_ip=10.255.255.1`; device UUID, serial, platform UUID,
  account, volume and proxy assignment stayed unchanged.
- `earnapp-v1182-us-mac-01` retains UUID
  `sdk-mac-e769907c101b5e1f4789794fccfd76b7`, account `2`, proxy `12709` and
  egress `116.98.185.18`. `earnapp-v1182-us-mac-02` retains UUID
  `sdk-mac-60e6ff13760ba2c72c56d8d25bc31ec5`, account `470`, proxy `12737` and
  egress `116.105.109.101`.
- Both exact runtimes now report `found 1 devs`, interface `en0
  (10.255.255.1)`, connected agent WebSockets and successful `tunnel_init`.
  A fresh authenticated account verification reports both exact UUIDs as
  `online=true`, `banned=false`, country `VN`, and the expected proxy egress.
  Usage remains zero immediately after recovery, so their status is
  `online_pending_usage`; do not mark EarnApp `PROTECTED_DONE` until positive
  usage/earnings is observed.
- The recovery exposed a stale persisted spec for macOS-02 with redacted proxy
  credentials. It was restored from the same authoritative proxy lease without
  rotation. Future full redeploy code must always rebuild credentials from the
  live lease rather than treating the redacted provider-instance spec as a
  replayable secret-bearing transport spec.
- Follow-up snapshots keep both exact UUIDs `online=true`, `banned=false`, and
  country `VN`. macOS-02 has now recorded positive usage `141` and therefore
  proves that the corrected profile can carry qualified workload; macOS-01
  remains online at zero usage and its observation window remains open.
  A controlled restart of macOS-01 preserved its container ID, UUID, account 2,
  proxy `12709`, volume, and image; the post-restart log again showed one
  detected `en0`, connected proxy/agent WebSockets, and successful
  `tunnel_init`. Authenticated link/collection immediately afterward still
  reported the exact UUID `online=true`, `country=VN`, and usage `0`, so link
  presence is confirmed but restart alone has not yet produced positive usage.
  macOS-02 had one transient proxy TLS
  reset and recovered its proxy/agent WebSockets without a lease change. Its
  container remains running with restart count `0` and no OOM. The 120-minute
  post-recovery usage window for macOS-01 therefore remains open; this is not
  sufficient evidence to mark the provider complete.
- PR #120 merged as `bf71f09`; Auto Release published and verified `v1.19.4`.
  Only test-US worker `3098` was upgraded to the `v1.19.4` worker digest. The
  worker is healthy with restart count `0`, and all six EarnApp canary
  containers retained their IDs/runtime state across the worker-only upgrade.
  The released recreate route now fetches the latest assigned MacOS/iOS
  identity asset and replaces only that read-only bind; it does not link,
  rotate, rewrite the UUID, or replace the persistent identity volume.

## EarnApp macOS-upgrade evidence and lifecycle gate (2026-09-04)

- Forensic review of `earnapp_macos_upgrade_20260904` confirms the upstream
  image changed SDK `1.605.415` to `1.660.577`, improved interface/local-address
  handling, filtered Docker bridge addresses, and added bounded tunnel-decline
  cooldown. It did not change UUID generation, OAuth/link behavior, or provide
  a blacklist bypass. The observed 100 MiB image also recorded cgroup OOMs and
  is not a safe default.
- The exhaustive verifier compared equal-size binaries and found `17,330`
  changed bytes across `104` ranges, all inside seven pkg `STORE_CONTENT`
  records. ELF/pkg structure, native runtime, VFS, BuildID and all identity/link
  surfaces are unchanged. The relevant behavior is limited to safe local
  address/interface fallback, a derived `tunnel_init` alias and reduced payload,
  full Docker bridge filtering (`172.16.0.0/12`), and a two-hour decline cap;
  wrapper restart cooldown remains bounded to 60-3,600 seconds.
- CashPilot release `v1.18.23` is deployed UI-only. The UI is healthy at the
  pinned digest and database integrity is `ok`; worker `1.18.16` and all
  non-UI containers remained unchanged.
- PR #114 adds fail-closed capability checks to heartbeat pending-proxy
  reconciliation and unhealthy-node rotation. Automatic EarnApp mutation now
  requires an online worker reporting `>=1.18.21`; lookup errors, old,
  unknown-version, and offline workers remain observation-only.
- Live test-US worker `3098` reports `1.18.21`. Historical test-sing worker
  `43406` reports `1.17.13`; post-deploy log sweep found no new proxy apply,
  finalize, or rotation request to that worker.
- Six test-US canaries remain unchanged and within scope. iOS (2) and Ubuntu
  (2) have positive usage; macOS-01 is online with zero usage during the
  propagation window, while macOS-02 is online in the authenticated snapshot
  but its persisted worker evidence is stale/error. No automatic mutation was
  run during this verification checkpoint.
- The verified operator artifact bundle is available outside Git at
  `earnapp_new_update/earnapp-runtime-files/mac-1.660.577`; its binary,
  boot script, and entrypoint hashes match the forensic report. A dedicated
  image `cashpilot/earnapp-mac-canary:asset-769bc08f7fc5` was built on
  `vps-test-us` and passed Dockerfile/syntax checks, but has not replaced a
  live node yet. Adoption remains limited to a bounded macOS canary with
  memory monitoring.
- During the bounded canary, the first image rollout exposed a stale wrapper
  checksum for the previous macOS binary, which removed the new binary and
  caused `/usr/bin/earnapp` exit `127`. The checksum contract was corrected to
  `d140b41a...d6911`, tests pass, and the test-US canary image was rebuilt with
  manifest `e949d13d7861`. mac-01 and mac-02 now run SDK `1.660.577` with
  unchanged UUIDs, volumes, account assignments, proxy egress and no OOM;
  usage verification remains pending.

## EarnApp v1.18.17 multi-platform canary reboot checkpoint (2026-09-04)

- `vps-test-us` was rebooted in isolation. All six canary containers returned
  automatically with restart policy `always`, restart count `0`, unchanged
  UUIDs, volumes, image lanes and DB proxy assignments. Worker `3098` remains
  on `1.18.17`; UI/worker key hashes still match and heartbeat remains healthy.
- Exact egress remained correct through the proxy sidecars. mac-01/mac-02,
  iOS-01/iOS-02 and Ubuntu-01/02 retained their expected proxy egress; mac
  runtime logs show Bright SDK proxy and agent WebSockets connected.
- mac-02's earlier `install_device` `504` was transient: proxy `12737` now
  probes alive over HTTP with expected egress `116.105.109.101`, while SOCKS5
  is not supported. A direct link retry returns `HTTP 200 / This device was
  already linked`, so no proxy rotation or identity change was performed.
- Fresh authenticated snapshots show all six canaries `online=true`; iOS and
  Ubuntu have positive usage/earnings, and both mac nodes now have
  `country_code=VN` but usage remains `0` during the initial propagation
  window. EarnApp is therefore not yet `PROTECTED_DONE`; continue the 120-minute
  usage gate before any recreate decision.
- Lifecycle scheduler fix is now covered by a regression test: every node with
  first zero-usage evidence persists `window_started_at`, so the 120-minute
  flatline gate cannot reset on each scheduler pass; positive usage resets the
  window and recovery counters.

## EarnApp Ubuntu reference closeout and worker mutation gate (2026-09-03)

- Fresh authenticated account evidence confirms all three Ubuntu reference
  nodes are now `online=true`, country `US`, and have positive qualified usage
  and earnings. Reference 01 reports `35,318,878 ms` / `$0.136`; reference 02
  reports `25,188,345 ms` / `$0.097`; reference 03 reports `16,328,630 ms` /
  `$0.062`.
- Reference 03 is `earnapp-ubuntu-reference-20260902-03`, device
  `sdk-node-371434603e7548fdb10c18935829181c`, proxy `13848`, and egress
  `130.180.232.61`. Its container remains running with restart count `0`, the
  named volume `earnapp-ubuntu-reference-20260902-03-data`, the same UUID, and
  matching observed egress. References 01/02/03 are successful protected
  baseline and must not be recreated, rotated, or used for further canaries.
- The production iOS trio is also online with positive usage. For the production
  MacOS trio, node 01 is online with positive usage, node 02's assigned UUID is
  absent from the authenticated account snapshot, and node 03 is present but
  offline with zero usage. Only MacOS 02/03 remain eligible for bounded repair;
  all nodes with positive usage are inspection-only.
- The MacOS 02 failure was traced to overlapping proxy-recreate requests. Docker
  returned `409 Conflict` for the stable container name after a heartbeat loaded
  pre-mutation state and later overwrote the new pending binding/container ID,
  allowing another request to enter the same recreate path.
- The source fix serializes EarnApp proxy apply/finalize per logical node,
  authenticates before allocating a lock, and makes heartbeat evidence refresh
  skip or reload around the same mutation boundary. Regression coverage includes
  concurrent apply, apply/finalize ordering, heartbeat stale-write protection,
  and unauthenticated request rejection.
- Fresh source verification on Python 3.14: focused EarnApp/proxy suite
  `439 passed`; full suite `2473 passed, 8 skipped`; Ruff check, changed-file
  format check, compileall, and `git diff --check` pass. This is still a source
  gate: the live worker remains on `v1.17.10`; no worker redeploy or live MacOS
  mutation has occurred for this fix yet.

## EarnApp multi-platform production hardening (2026-09-01, source gate)

- Current branch `feat/earnapp-production-hardening` adds the approved geo
  matrix: VN residential -> dedicated macOS/iOS Docker lanes; non-VN
  residential -> dedicated Ubuntu Docker lane. Generic/raw EarnApp deploy
  remains fail-closed.
- Proxy changes now recreate only the EarnApp main container. The existing
  identity volume, env, labels, UUID/device ID and resource limits are copied
  from the live inspect contract; the old container is restored on failed
  replacement. Non-EarnApp sidecars retain their prior restart behavior.
- Link verification is serialized per account, has a 5-second minimum relay,
  and uses a 300-second cooldown after every five-attempt burst.
- Ubuntu fresh identity now matches the audited 22.04.5 profile contract:
  `host.json`, `host.serial`, machine-id, release/interface/model/CPU/memory
  fields, unique `sdk-node-<32 hex>` ID, and optional `earnapp-host ensure/apply`.
- Fresh source evidence: focused EarnApp/proxy tests `411 passed`; full suite
  `2435 passed, 8 skipped`; Ruff, compileall and `git diff --check` passed.
  No release, deploy, VPS mutation, account change, protected-node mutation or
  provider outside EarnApp has occurred in this source gate.
- Next authorized live step is sequential canary only: 3 macOS + 3 iOS on
  distinct VN residential leases, then 3 Ubuntu on distinct non-VN residential
  leases. Each node must prove exact UUID, account link, online state and
  positive usage before closeout.

## EarnApp Ubuntu reference canary restart verification (2026-09-02)

- Canary `earnapp-ubuntu-reference-20260902-01` was restarted in place only;
  no node, account, lease, proxy, volume or provider outside this canary was
  changed. The container stayed `running` with restart count `0`.
- Restart persistence proof: the container ID, named volume
  `earnapp-ubuntu-reference-20260902-01-data`, and generated device UUID
  `sdk-node-335d82dec8be4388bf643267bc32846c` were unchanged. The worker-side
  egress remained `207.228.29.7` (US residential), matching proxy lease `13801`.
- Fresh authenticated collector evidence after restart reports the exact UUID
  present, `online=true`, `banned=false`, `country_code=US`,
  `billing=qualified_uptime`, `usage_current=845068`, `usage_total=845068`,
  `usage_points=7`, and `earned_total=0.003`. Persisted workload state remains
  `workload_verified`; no new link or identity operation was needed.
- This closes the bounded restart-persistence check for the reference canary.
  It does not authorize the planned 3+3+3 production canary rollout; that
  remains a separate, explicitly approved operation.

Updated: 2026-08-31 (EarnApp Ubuntu canary 5 TLS/transport investigation)

## EarnApp Ubuntu Docker migration (unreleased, 2026-08-31)

- Source changes now route new Ubuntu EarnApp deployments through the dedicated
  Docker lane using the pinned official Linux binary image
  `cashpilot/earnapp-ubuntu:asset-f52fb20750d1`.
- Ubuntu identity profiles generate unique `id`, `serial`, `machine_id`,
  hostname and `sdk-node-<32 hex>` device IDs per logical node. The image
  removes `/.dockerenv`, persists `/etc/machine-id` and `tracking_id`, validates
  proxy egress, and retries `install_device`/`is_linked` before starting the
  official runtime.
- New and replacement EarnApp nodes are Docker-only across Ubuntu, macOS and
  iOS. Legacy LXD heartbeat records remain readable as evidence only; deploy,
  recreate, recovery and proxy mutation reject LXD.
- Regression evidence for this source change: Ruff, compileall and 513 focused
  EarnApp/provider tests pass. No release, worker redeploy, VPS mutation,
  proxy rotation, identity rewrite or existing node mutation has occurred yet.
- Live canary remains pending on `test-sing`: remove/recreate only the Ubuntu
  canary after release, preload the pinned image, then verify Docker runtime,
  exact UUID/egress, `linked:true`, country, positive usage and restart/reboot
  persistence. Protected nodes and providers remain untouched.

## EarnApp Ubuntu canary 5 investigation (2026-08-31)

- Current target is only `earnapp-ubuntu-canary-test-sing-5`, LXD
  `cashpilot-earnapp-earnapp-ubuntu-canary-test-sing-5`, device
  `sdk-node-2a7f6d1a0695feb31485a559fc6f0137`, account `2`, generation `1`,
  proxy `13746`, egress `64.52.28.108`. Do not mutate node 4, NKN, MYST or any
  other protected provider/node/lease/identity/volume.
- Fresh read-only checks show the LXD guest and both services running, the
  exact UUID present in the authenticated five-device list, and the server
  lease/observed egress unchanged. The node is not complete: authenticated
  daily usage remains zero for 2026-08-24 through 2026-08-30, and the status
  endpoint does not report the exact UUID online.
- Chrome profile 40 confirms the authoritative remote symptom:
  `sdk-node-fc6f0137` has blank country, `0s` usage and `$0`; the other Ubuntu
  row `sdk-node-a4addc8f` is also at `0s`, while protected Mac/iOS devices have
  positive usage. Local process/service health is not an online/usage proof.
- The operator's earlier TLS failure is tracked as a valid hypothesis. Strict
  TLS 1.3 CA/SNI checks and a strict WSS `101` handshake currently succeed
  through proxy `13746`; the live SPKI matches the historical pin and the
  current pin document. Guest CA/time state is valid. No general TLS failure
  has been reproduced.
- Proprietary binary pinning/handshake behavior is not fully observable, so
  TLS remains residual uncertainty. Do not disable certificate verification,
  remove pinning or treat `NODE_TLS_REJECT_UNAUTHORIZED` from the historical
  Apple Docker build as applicable to the native Ubuntu ELF.
- Proxy `13746` rejects SOCKS5 UDP ASSOCIATE (`reply=7`), its `udp_ok` is
  unknown, the guest rejects non-DNS UDP, and the catalog says
  `egress.udp: none`. No current non-VN residential EarnApp candidate has
  verified `udp_ok=true`. UDP requirement remains an investigation hypothesis,
  not a confirmed root cause or permission to rotate the lease.
- sing-box supports UDP on SOCKS/TUN, including optional UDP-over-TCP, but the
  current CashPilot guest deliberately blocks non-DNS UDP. This is a concrete
  runtime/reference difference and the next bounded hypothesis to test only
  after an impact map and a rollback-preserving node-5 A/B design.
- Read-only UDP ASSOCIATE probes for candidates `13746`, `13751`, `13754`,
  `13781`, `13752`, `13768` and `13773` all returned SOCKS reply `7`. Rotating
  node 5 among them would not change UDP capability. sing-box UoT is
  proprietary and requires a compatible server; do not enable it against this
  ordinary third-party SOCKS pool without server-side proof.
- Existing uncommitted retry code for `install_device` plus `is_linked` is not
  sufficient to close the gate because the device is already registered while
  usage is zero. Do not release/deploy it until the online/usage failure is
  explained and the retry contract is re-reviewed against that evidence.
- Protected rollback artifacts for node 5 are LXD snapshots
  `pre-singbox-ab-20260830T185328Z` and
  `pre-singbox-ab-20260830T195303Z`. No release, proxy rotation, identity
  rewrite, recreate, account mutation or provider change occurred in this
  investigation.

## Current source policy (unreleased, 2026-08-29)

- The current worktree changes EarnApp to a geo-platform runtime policy:
  qualified VN residential proxies use the dedicated MacOS/iOS Docker lanes;
  qualified non-VN residential proxies use the official Linux x64 Ubuntu LXD
  lane.
- Generic catalog deploy, raw Docker deploy and caller-supplied platform
  metadata on generic routes remain blocked; only dedicated server/worker
  platform contracts may deploy or mutate a node.
- Ubuntu nodes retain sequential auto-deploy, non-VN residential proxy
  selection, account binding, one-hour recovery hold, one-time replacement
  tickets, CAS lifecycle and proxy rotation/reconciliation. Settings
  `earnapp_lxd_cpu` and `earnapp_lxd_memory_mib` are authoritative for new
  guests.
- The official EarnApp help article, updated 2026-07-30, states that Linux x64
  on a 64-bit OS is supported, Ubuntu 20.04 is the tested distribution, the
  Bright Data installer is authoritative, and the installed service starts on
  reboot. The pinned installer SHA-256 in the host helper was rechecked against
  the current official download and still matches.
- This source-only gate change does not alter the v1.14.1 live fleet evidence
  recorded below. No release, deploy, VPS mutation, proxy lease, account,
  identity or existing EarnApp node was changed in this worktree.

## v1.14.1 compliance rollout closeout (2026-08-29)

- PR #55 merged as `21b4f90765cb98cfc97c753ea6e9f2ab6fc3e599` and
  Auto Release run `33241201751` published `v1.14.1`. Post-merge Catalog
  Check, CodeQL, Documentation, Lint, Tests and Auto Release all completed
  successfully. The published UI and worker digests are respectively
  `sha256:f8291ff7ecae02981edbdfd987ad3a45e3386efa9a843004148ad7773b38b552`
  and
  `sha256:09550bc1098eccd8dbef04b1b0d7e665196e460ef25414f25d4d856e078140f0`.
- The server UI was recreated alone and is healthy on `v1.14.1`, restart count
  `0`, with the existing `cashpilot_cashpilot_data:/data` and
  `cashpilot_cashpilot_fleet:/fleet` volumes unchanged. SQLite remains schema
  `21` with `integrity=ok` and zero foreign-key violations. The live runtime
  matrix returns `deployment_allowed=false` and
  `deployment_policy=vps_runtime_prohibited`; both generic deployment and
  existing-runtime mutation checks block EarnApp instances.
- Collection remained available through the compliance gate. The active
  account's fresh redacted snapshot reports balance/total `2.511`, online
  `3`, offline `1`; the legacy account remains `DISABLED`. No credential was
  rendered during verification.
- Only `cashpilot-worker` on `test-sing` was recreated, with `--no-deps`, from
  the pinned worker digest above. It is healthy on `v1.14.1`, restart count
  `0`, and retains the existing `/data`, public-IP-slot, NKN-agent,
  EarnApp-agent and Docker-socket mounts. The persisted worker ID and signing
  key hashes, plus the public-IP-slot hash, are unchanged.
- Server worker row `43406` remains online with confirmed enrollment and a
  fresh `v1.14.1` heartbeat. The NKN LXD instance remains `RUNNING`; its inner
  official NKN container ID, one-CPU/one-GiB limits, wallet `#1`, lease client,
  assignment version `3`, node identity and runtime evidence are unchanged.
  Both NKN and EarnApp host agents remain enabled and active.
- All nine existing EarnApp containers and sidecars retained their exact IDs,
  images, state, restart counts and mounts. The three active leases remain
  bound to the same logical nodes and proxies: Mac node 1 to `#12706`, Mac
  recovery node 2 to `#12708`, and iOS node 3 to `#12724`. No EarnApp node,
  sidecar, volume, identity, proxy or account binding was deployed, stopped,
  restarted, recreated, rotated, released, recovered, unlinked or deleted.
- Protected operational backups are
  `/opt/cashpilot/backups/v1.14.1-ui-predeploy-20260829T075511Z` on the server
  and
  `/opt/cashpilot-worker/backups/v1.14.1-worker-predeploy-20260829T081122Z`
  on `test-sing`. They contain compose/inspect evidence and data snapshots;
  credentials remain protected and were not added to Git.

## v1.14.1 live EarnApp status (historical deployed baseline)

- **Historical v1.14.1 status:** `COMPLIANCE_BLOCKED` / `RUNTIME_DISABLED` for
  all new VPS runtimes. That released build treated EarnApp terms as prohibiting
  virtual machines, containers and hosting services, so it did not create new
  Docker, LXD or other hosted nodes. This paragraph records the deployed
  v1.14.1 baseline; the unreleased source policy above now authorizes only the
  dedicated official Ubuntu x64/LXD lane.
- The Account Pool and collector remain enabled. The operator refreshed the
  account token; the server stores only encrypted credentials and exposes only
  expiry/status metadata. A token refresh restores collection only and does not
  authorize a new hosted node.
- Fresh collection-only verification after the refresh and rollout returned
  `status=ok`, balance/total `2.511`, online/offline `3/1`, and a healthy existing account
  route on proxy `#12706`. The token expiry remains `unknown` because the
  refreshed credential did not expose parseable expiry metadata. No runtime or
  lease mutation was performed by this check.
- Existing EarnApp nodes are inspection-only and immutable. Do not recreate,
  migrate, rotate, unlink, delete or alter their identities, volumes, sidecars,
  account bindings or leases through this policy change.
- Generic deploy, platform-canary deploy, Ubuntu-LXD deploy and EarnApp
  auto-deploy fail closed before worker, slot, proxy or lease calls. Collection,
  historical snapshots and existing-node inspection remain available.
- Older sections below describe historical canary states. They are retained for
  auditability; the unreleased source policy at the top is the current code
  authorization.

## EarnApp platform canary investigation (historical, 2026-08-28)

- At this historical checkpoint, the investigation reopened platform validation without changing the
  immutable baseline. The existing Docker nodes `earnapp-canary-test-sing-1`
  and `earnapp-recovery-test-sing-2` must not be recreated, migrated, rotated
  or deleted; their containers, sidecars, volumes, identities, account binding
  and leases remain protected.
- Fresh authenticated usage data corrects an earlier diagnostic mistake: node 1
  has positive current-day qualified usage (`32,740,937 ms` on 2026-08-28),
  while node 2 has only `18,142 ms` and is near a workload plateau. Both devices
  are present, online and not banned. Online status alone is not a workload
  success gate.
- The evidence does not establish Docker as the root cause. Node 1 has WSS
  timeout/proxy `502` signals; node 2 has a clean route but little workload, so
  control-plane allocation/eligibility remains an open hypothesis.
- New canaries are disposable only: iOS uses a fresh Docker node with a VN
  residential lease; Ubuntu uses the official runtime in a fresh LXD guest with
  a non-VN residential lease. Each must prove authenticated presence, online
  state, positive workload delta, identity persistence and exclusive proxy
  ownership.
- MacOS/iOS remain Docker-only. Apple-platform LXD conversion is outside the
  approved design and has no deploy or experimental-spec path in CashPilot.
- Historical status only: EarnApp remained open for platform closeout until
  iOS and Ubuntu-LXD canaries could pass all gates. The current compliance gate
  supersedes that authorization. NKN, MYST and other `PROTECTED_DONE`
  providers are unaffected.

## EarnApp v1.13.4 closeout (historical runtime baseline, 2026-08-28)

- PR #52 merged at `8d2b86087c4cefc8e256aa8e359e2b2829c8af3e` after
  CodeQL, Ruff and the full GitHub test suite passed. Auto Release run
  `33137032952` published `v1.13.4`; the worker manifest is
  `sha256:9e8e3e20f671fd775aa4443ba9d0b63b11fcb90bb63a96cb549213f9ed7e695f`.
- The release fixes EarnApp proxy rotation when the main container uses
  `network_mode=container:<sidecar-id>`. After each EarnApp sidecar restart,
  the worker validates the exact sidecar ID/name and restarts only the matching
  main container so it joins the new network namespace. Apply, explicit
  rollback and internal rollback are regression-covered; non-EarnApp sidecars
  keep their existing behavior.
- Only `cashpilot-worker` on `test-sing` was recreated, with `--no-deps`, from
  the pinned v1.13.4 digest. Its persisted worker ID/key hashes were unchanged,
  the server received a fresh authenticated `1.13.4` heartbeat, and all EarnApp
  and NKN runtime lifecycle snapshots were unchanged by the worker rollout.
- `cashpilot-ui` intentionally remained on the verified v1.13.2 digest because
  this fix executes inside the remote worker's sidecar orchestration path; no
  server-side schema, route or scheduler change was required for the gate.
- Protected node `earnapp-canary-test-sing-1` remained inspect-only throughout:
  container `346712d55ab6`, sidecar `59dc3b1034ac`, volume
  `earnapp-canary-test-sing-1-data`, device
  `sdk-mac-84809cc96464d92c8a2786714ae944b1`, proxy `12706`, egress
  `171.251.97.103`, start times, restart counts and machine ID were unchanged.
- Disposable node `earnapp-recovery-test-sing-2` retained container
  `075ad5d045a6`, sidecar `dbc24f66d495`, volume
  `earnapp-recovery-test-sing-2-data`, generation `1`, account `2`, device
  `sdk-mac-9e2dfc3d266d95b951cc24e5f5ab3142` and machine ID while two isolated
  rotations succeeded. The first changed proxy `12708`/`116.98.176.124` to
  `12724`/`14.236.137.88`; the second selected the prior proxy by affinity and
  returned to `12708`/`116.98.176.124`. Main networking retained `eth0`, routes
  and DNS after both sidecar restarts.
- Authenticated EarnApp evidence reported both device IDs present, online and
  not banned. The account snapshot was balance `$2.284`, online `2`, offline
  `0`. Final database state is `integrity=ok`, foreign-key violations `0`,
  active rotation reservations `0`, and exactly two active EarnApp leases.
- Server backup is
  `/opt/cashpilot/backups/earnapp-v134-rotation-20260828T030039Z`; worker/runtime
  snapshots are under
  `/opt/cashpilot-worker/backups/earnapp-v134-rotation-20260828T030039Z` and
  `/opt/cashpilot-worker/backups/v1.13.4-worker-deploy-20260828T025707Z`.
- At this checkpoint EarnApp became `PROTECTED_DONE`. The 2026-08-29
  compliance decision supersedes deploy authorization: it remains a protected
  historical baseline, but hosted runtime is now `COMPLIANCE_BLOCKED` /
  `RUNTIME_DISABLED`. Do not use either successful live node as a destructive
  test.

Updated: 2026-08-28 (historical v1.13.2 checkpoint; recovery gates were open at this release)

## EarnApp v1.13.2 scoped live rollout (historical checkpoint, 2026-08-28)

- PR #48 merged at `ba2d29dda746327e0db445239244e12c684d9e03` and Auto
  Release run `33104948032` published `v1.13.2` from that merge. Post-merge
  Catalog Check, CodeQL, Lint, Tests and Auto Release all completed
  successfully.
- Registry verification resolved the UI image to
  `sha256:83a5b98c698d4ac59513d72108d516581e58be2895dcf9351ee68d77fc8ce913`
  and the worker image to
  `sha256:03419892ec982acb240d13b6238bbb9a6ea15f36ff1db281d39e8fb20a73e1a7`.
- Before the live change, a consistent server SQLite backup was written to
  `/opt/cashpilot/backups/earnapp-v132-authority-backfill-20260827T192358Z`.
  The approved metadata-only backfill set the legacy canary to
  `platform=macos` and `expected_egress_ip=171.251.97.103` after correlating
  database state, the active lease, proxy evidence, encrypted spec and running
  container labels. Account, worker, generation, device identity and lease did
  not change.
- Only `cashpilot-ui` on the server and `cashpilot-worker` on `test-sing` were
  force-recreated without their dependencies. Both report version `1.13.2` and
  healthy state. The UI database remains at schema `21` with `integrity=ok` and
  zero foreign-key violations.
- Worker row `43406` retained persisted client ID
  `e2a103a007d7e7c93172de6505e2e14839519dca4176989561dcf6f827a0871c`.
  The signing-key file was verified unchanged without recording its secret
  value. Fresh authenticated heartbeats arrived at `2026-08-27 19:30:18 UTC`
  and `2026-08-27 19:31:21 UTC`.
- The live node remains `earnapp-canary-test-sing-1`, Account Pool id `2`
  (`assetforgeai`), platform/backend `macos`/`docker`, proxy lease `#12706`, and
  egress `171.251.97.103`. The runtime image remains
  `cashpilot/earnapp-mac-canary:asset-4a1e80cbb95d`. Container
  `cashpilot-earnapp-canary-test-sing-1`, sidecar
  `cashpilot-earnapp-canary-test-sing-1-egress`, volume
  `earnapp-canary-test-sing-1-data`, account binding, generation and device
  identity were preserved. Fleet reports online `1`, offline `0`, with healthy
  runtime state.
- Chrome profile 40 remains authoritative. It shows account `AssetForge AI`,
  balance `$2.284`, device `sdk-mac-4ae944b1`, country `VN`, and active usage.
  This is the remote-account evidence; container health alone is not treated as
  proof of a linked online device.
- NKN LXD, Mysterium and all other `PROTECTED_DONE` providers, their containers,
  volumes, identities, proxy/wallet leases and runtime state were not changed.
- At this v1.13.2 checkpoint EarnApp was not yet `PROTECTED_DONE`; the remaining
  gates were restart/recovery persistence and isolated proxy rotation on a new
  disposable canary. The v1.13.4 closeout above supersedes that open status.

Updated: 2026-08-26 (EarnApp v1.11.2 legacy migration live closeout complete)

## EarnApp v1.11.2 legacy migration live closeout (2026-08-26)

- PR #42 merged as `a6c6e4c18a7e4fdfca7b00396bbb51f6f6f2e849`. Auto Release run
  `32902222108` passed and published `v1.11.2`; the tag resolves to the same
  merge commit. All post-merge Catalog, CodeQL, Documentation, Lint and Tests
  workflows also passed.
- Migration runs in one `BEGIN IMMEDIATE` transaction and rolls back on any
  schema, archive, conflict or `foreign_key_check` failure. Legacy account and
  lease data remain in `earnapp_accounts_legacy_v18` and
  `earnapp_account_leases_legacy_v18`; interrupted v19 sources remain in
  `earnapp_accounts_v19_legacy` rather than being discarded.
- Completion is fail-closed: the marker
  `migration.earnapp_accounts.legacy_v19=complete` is accepted only when the
  canonical account schema, child tables, primary keys, indexes, unique keys,
  foreign keys, archive parity and row identities still match the contract.
  Unknown child tables, external trigger references, duplicate archive IDs and
  conflicting partial rows abort without committing.
- Legacy accounts are never silently activated. Legacy active leases become
  deterministic `RECOVERABLE` logical nodes, while account credentials remain
  encrypted and are adoptable only through an explicit Chrome import. Fernet
  values are compared by decrypted plaintext during interrupted-copy recovery,
  so normal token re-encryption does not create a false conflict.
- Regression coverage includes transaction rollback, archive preservation,
  canonical/child schema validation, FK/index/trigger preservation, marker
  validation, duplicate/conflicting archive detection, synthetic-account
  quarantine and Fernet-equivalence checks. No provider catalog/runtime source,
  proxy lease, wallet lease, identity or provider volume changed.
- Fresh local verification: focused EarnApp/Chrome/proxy/UI suite `369 passed`;
  full non-live suite `1854 passed, 8 skipped` after fetching the fork tag
  refspec used by CI. Ruff lint, compileall, JavaScript parse, deploy-baseline
  and `git diff --check` pass. Repository-wide Ruff format still reports only
  the unchanged historical plan file
  `docs/superpowers/plans/2026-08-25-proxy-import-protocol.md`.
- A consistent SQLite backup plus encryption/session keys and compose evidence
  was created at
  `/opt/cashpilot/backups/v1.11.2-earnapp-migration-20260825T214804Z` before
  deploy. Pre-migration DB evidence was `integrity=ok`, zero FK violations, one
  legacy `VALID` account and three legacy `ACTIVE` leases.
- Only `cashpilot-ui` was recreated, using UI digest
  `sha256:31d17ca6ba17a55ae6f15686bc945a1ed12dfad29ce87f1ed71fa2ef8605086d`.
  It is healthy, reports `CASHPILOT_VERSION=1.11.2`, restart count `0`, and
  serves the normal root redirect. The v1.11.2 worker image was published by
  the release contract but was not deployed.
- Live migration retained the immutable v18 archives (`1` account, `3`
  leases), materialized one canonical account as `DISABLED`, created three
  deterministic `RECOVERABLE` logical nodes, and wrote marker
  `migration.earnapp_accounts.legacy_v19=complete`. Integrity remains `ok`, FK
  violations remain `0`, and the second controlled UI boot logged
  `Schema at version 19; no migration needed this boot.`
- Worker `60b180133540` kept its custom image, start time and restart count `0`;
  the fingerprint of every non-UI container stayed unchanged. Counts for
  workers/provider instances/MYST wallets/NKN wallets remained
  `3 / 29 / 6266 / 26021`. No worker/provider runtime was redeployed.

## EarnApp account/recovery implementation (merged baseline, 2026-08-25; historical checkpoint)

- PR #40 merged as `102fa9e1e163a9cb0ebd7715da19a19a33e17b51`; its implementation
  commit is `9968a853ba5523c4bd96fa61e98473583c6a7e46`. At this historical
  checkpoint the control plane was merged, while the official runtime/live
  canary work was intentionally still open.
- The server now has an isolated EarnApp Account Pool: Google/Apple metadata,
  Fernet-encrypted allowlisted cookies, masked owner APIs, token/cookie expiry
  warnings, least-assigned account allocation, account-scoped read-only
  collection, proxy capacity and logical-node recovery state. Schema is `19`.
- Recovery starts only after the existing `900s` stale-worker threshold.
  `RECOVERY_HOLD` is exactly `3600s` (one hour): the original proxy remains
  exclusive during the hold; after expiry its lease is released but
  `preferred_proxy_id`, account binding, device identity and logical node are
  retained. A different worker requires a one-time ticket plus generation/CAS;
  CashPilot never automatically unlinks or deletes the remote EarnApp device.
- EarnApp routes require a generic-live, canonical residential proxy whose
  latest matching-egress EarnApp WSS evidence is `CID_SET` and `eligible`.
  Collection uses a proxy belonging to that account; before node one, a
  dedicated account-control route is leased and then transferred atomically.
  Proxy Pool selected/status/all deletion removes transient control-route rows
  in the same transaction while preserving EarnApp accounts and credentials.
- The Chrome Manifest V3 importer reads only `auth`, `auth-method`,
  `oauth-refresh-token`, `oauth-token`, `xsrf-token`, `brd_sess_id` and
  `cg_uuid` from EarnApp. First import is explicit; subsequent cookie/startup/
  15-minute synchronization applies only to the bound account. Both ordinary
  provider imports and EarnApp sync now use one authenticated HTTPS CashPilot
  origin under `4gmt.com`; the legacy plaintext HTTP/IP destination is removed.
  Provider collectors still use their official upstream APIs. Google and Apple
  cookies are never read, displayed or logged.
- EarnApp capacity and account-control allocation exclude legacy assignments,
  active scoped leases and active control routes by both endpoint ID and
  canonical egress IP, including duplicate rows that have not yet been marked.
- Final pre-PR hardening makes replacement-ticket creation a transactional
  compare-and-swap: the node must still be in `RECOVERY_HOLD`/`RECOVERABLE`,
  generation must match, and the target worker must exist. A heartbeat from the
  original worker atomically cancels recovery metadata and revokes outstanding
  same-generation tickets. Claims are rejected after the node is active again.
- EarnApp capacity is reported as distinct eligible/leaseable egress IPs, not
  endpoint rows. The Chrome importer catches invalid CashPilot URLs inside its
  visible error path, and cookie-change debounce uses a separate one-shot alarm
  so it cannot overwrite the recurring 15-minute token-sync schedule.
- The merged baseline's earlier verification was `283 passed` focused and
  `1812 passed, 8 skipped` full; the current migration-safety branch's fresh
  verification is recorded in the section above.
- Historical checkpoint only: official catalog/runtime, MacOS/iOS emulation,
  Ubuntu LXD deployment, worker provision/follow/link automation, DNS/reverse
  proxy provisioning, Chrome validation and the live canary had not yet been
  completed. See the v1.13.4 closeout section above for the current protected
  state.

## v1.10.0 Proxy Pool metadata/location live closeout (2026-08-25)

- PR #38 merged at `30ab8a2b4e4915deba9ed216e1b6fa7c47ea91ad`; Auto Release run
  `32837209953` completed successfully and published `v1.10.0`.
- Only `cashpilot-ui` was redeployed. It is healthy at digest
  `sha256:f62032cc8e0cac986c02ed2b1760b1f175942a4a0a2b4a9309d1c6f6828798c0`;
  restart count is `0`. `cashpilot-worker` kept its existing container,
  image, start time, health, and restart count; no worker/provider runtime was
  changed.
- The final authenticated read-only snapshot contains `1,004` rows:
  `1,000` generic-live and `4` generic-dead; `1,000` known egress and `4`
  unresolved; `0` location pending, `0` IP-type pending, and `0` aggregate
  metadata pending. Duplicate egress rows are `161`; canonical available is
  `839`; active assignments and scoped leases are both `0`.
- All `1,000` known egress rows have `country_code=VN` and `ip_type=residential`.
  The API/filter machine key is ISO alpha-2 `VN`; the UI derives the readable
  label `Vietnam`. The four dead rows stay `Generic check failed`/unknown
  because no authoritative egress exists.
- EarnApp evidence is independent of Location: `306` eligible, `273`
  leaseable, `881` checked, `119` not checked, and `4` skipped due to generic
  failure. Lease selection still requires canonical egress, no assignment or
  lease, and latest `CID_SET` evidence.
- The one-IP canary and bounded metadata-only refresh persisted geo/IP-type
  evidence without generic/EarnApp rechecks, rotation, lease/release,
  assignment, duplicate cleanup, credential changes, wallet operations, or
  provider actions. Full evidence is in
  `docs/research/proxy-pool-metadata-location-live-closeout.md`.
- The old screenshot with many `Metadata pending`/`unknown` chips is a
  pre-closeout capture; it is not current live state. The remaining safe data
  quality item is limited to the four generic-dead rows.

## v1.9.0 Proxy Pool import-protocol live closeout (2026-08-25)

- PR #36 merged at `eb3da8b1663af352a6386fef1d170d7e36784db7`; Auto Release
  published GitHub tag `v1.9.0` and registry image tags `1.9.0`/`1.9`.
- The UI-only change adds a request-scoped import selector: `Auto`, `HTTP`, or
  `SOCKS5`. Auto preserves SOCKS5-then-HTTP detection; a forced choice applies
  only to the initial generic import check, while later scheduler/manual
  rechecks remain automatic. No provider, worker, lease, wallet, identity,
  migration, or live proxy-row code was changed.
- Live `cashpilot-ui` is healthy at digest
  `sha256:9fb1593d7bcd6378d0ab97be96afd598112ac13826983867a422b8750592d717`,
  reports `CASHPILOT_VERSION=1.9.0`, and has restart count `0`. The UI was
  recreated with `--no-deps` and the existing volumes/network/ports.
- `cashpilot-worker` remains container `60b180133540`, image
  `cashpilot-worker-local:proxy-egress`, start time `2026-08-20T09:04:41Z`,
  restart count `0`, and healthy. It was not pulled, recreated, restarted, or
  redeployed. Database integrity remains `ok`.
- Read-only browser verification passed at desktop `1280px` and mobile `375px`:
  no document overflow, selector default `auto`, options `Auto`/`HTTP`/`SOCKS5`,
  visible label `Protocol`, and a `44px` control.
- The full read-only Proxy Pool sweep found `1,004` rows over `11` stable
  pages, `1,003 alive / 1 dead`, `0` duplicate row IDs, HTTP protocol only,
  provider `zlproxy` only, and `0` active worker/instance bindings. Scheduler
  is currently disabled at `60` minutes/concurrency `32`.
- Live data-quality state is materially different from the older `v1.8.1`
  snapshot: all `1,004` rows lack country/location and IP-type metadata;
  `306` EarnApp rows are `CID_SET` eligible, `578` are `BLACKLIST` blocked,
  and `120` have no EarnApp evidence. Duplicate reconciliation marks `164`
  rows across `145` egress groups, with canonical IDs present for all marked
  rows.
- Full evidence and bounded recommendations are recorded in
  `docs/research/proxy-pool-v1.9.0-live-audit.md`. No live import, recheck,
  delete, rotation, lease, release, assignment, or metadata normalization was
  performed during the audit.

## v1.8.1 Proxy Pool live closeout (2026-08-25)

- PR #33 merged at `098ac2b3eee1a77b09ec7855c328485f9ce7ef0a` and published
  `v1.8.0`. The audit then found the `dawn_dashboard_session` masking gap. PR
  #34 merged the isolated fix at `a3d2dce4bef66fdc1053fefda38cdbde3b422ed7`;
  Auto Release run `32817037347` completed successfully and published `v1.8.1`.
- The server `cashpilot-ui` is healthy on the verified UI digest
  `sha256:3ba1e9b4ba1cfb7e24eb9e8df47257953d4474f2dcdc29799c3a40ebeb22244d`;
  container `0e67b499ff69`, `CASHPILOT_VERSION=1.8.1`, restart count `0`.
  UI override `/opt/cashpilot/docker-compose.ui-v1.8.1.override.yml` has SHA-256
  `fab6b15055a05a682a0571da8830d2f607767f34cc4c03b9e1d92cc0b830da25`.
- `cashpilot-worker` remained container `60b180133540`, image
  `cashpilot-worker-local:proxy-egress`, start time
  `2026-08-20T09:04:41.088040401Z`, restart count `0`, and healthy. The
  worker was not pulled, recreated, restarted or redeployed. DB integrity is
  `ok`, schema `18`.
- A fresh authenticated read-only sweep retrieved all `3,223` proxy rows over
  `33` bounded pages (maximum `100` items; maximum payload `117,744` bytes).
  Generic alive/dead is `1,844 / 1,379`; egress known/unresolved is
  `1,844 / 1,379`; country known `1,831`; IP type known `1,020`; metadata
  pending aggregate `824`; duplicate egress rows `755`; canonical usable and
  available are both `1,089`.
- EarnApp evidence counts are eligible `922`, leaseable `338`, checked `1,793`,
  not checked `51`, and skipped because the generic check failed `1,379`.
  Active legacy and scoped leases are both `0`. Scheduler remains enabled at
  `60` minutes/concurrency `64`. No import, delete, recheck, rotation, lease,
  release or assignment was performed.
- Authenticated Playwright checks passed on desktop `1440px` and mobile
  `375px`: no page overflow, bounded server pagination, search/filter/sort and
  pagination requests, correct ARIA sort transitions, and no console/page
  errors. The mobile table's inner horizontal scroll is intentional.
- Endpoint map and redacted evidence are recorded in
  `docs/research/proxy-pool-v1.8.0-live-audit.md`. The pre-fix audit found one
  security gap: `dawn_dashboard_session` was populated in `/api/config` but was
  not classified into `_secrets`; its value was not copied into docs. The
  `v1.8.1` authenticated proof confirms that the key is absent from the
  ordinary config map and present only as `_secrets.dawn_dashboard_session =
  true`. No credential was rotated or deleted.
- Two data-quality follow-ups remain design-only: canonicalize `VN`/`Viet Nam`
  labels (`39 / 1,542` rows in the closeout snapshot) and plan a
  freshness-aware EarnApp re-probe. Do not bulk mutate either until an impact
  map and explicit approval exist.

## Current repository state

- Historical repository/deployment checkpoint: canonical source and tag
  `v1.13.2` both resolved to merge `ba2d29d`; the live
  server UI and `test-sing` worker are verified on the v1.13.2 digests recorded
  in the scoped-live section above. The deployment was limited to those two
  CashPilot components and the existing EarnApp canary.
- At that checkpoint schema was `21`; the server database integrity check was
  `ok` with zero foreign-key violations. EarnApp platform/device identity
  remains immutable per logical node. Recovery/rotation mutation gates are now
  closed by the current inspection-only policy.
- PR #27 upgrades the reported SQLite schema from 17 to 18 through
  idempotent guards. A migration regression starts from a populated v17 proxy
  schema and verifies that endpoints, worker assignments and provider masks are
  retained while the new intelligence, evidence, import and scoped-lease
  structures are added.
- The original direct-runtime and Docker canary history is retained for
  traceability. The LXD runtime landed through PR #17, guarded canary adoption
  through PR #18, the adoption timeout fix through PR #19, and the optional
  ChainDB acceleration through PRs #21-#24.
- Release `v1.6.1` is published and verified. PR #21 added the snapshot
  publisher/consumer contract, PR #22 fixed the release image build context, and
  PR #23 added publisher compatibility with the VPS's Python 3.10 runtime.
- PR #1 (Grass retirement), PR #2 (fork GHCR images), PR #3 (fork install
  surfaces), PR #4 (redacted historical evidence), PR #5 (current context),
  PR #6 (read-only baseline refresh), PR #7 (proxy worker ACK rotation), PR #8
  (post-merge baseline), PR #9 (`v1.2.0` canary context), PR #10 (NKN direct
  runtime), PRs #11-#13 (NKN canary fixes), PRs #14-#16 (NKN context history),
  PRs #17-#19 (LXD runtime, adoption and timeout fix), and PRs #21-#23 (ChainDB
  acceleration and release/runtime fixes), PR #24 (shared ChainDB cache), and
  PR #25 (bootstrap and standalone NKN host-helper closeout), PR #26 (NKN
  `v1.6.3` live context), PR #27 (Proxy Pool qualification), PR #28
  (persisted-egress intelligence fix), PR #29 (EarnApp probe TLS contract), PR
  #30 (v1.7.2 live closeout), PR #31 (import enrichment), PR #32 (lease safety),
  PR #33 (server-side pagination/UI hardening), and PR #34 (dashboard-session
  masking) are merged.
- Release `v1.6.3` is published from merge commit `f5ee981`; Auto Release run
  `32720862355` completed successfully and built both fork GHCR images. The UI
  digest is
  `sha256:7434350e08a622789ff67efb52d73bf5b88866510cf61c04603471201e9c86aa`
  and the worker digest is
  `sha256:69e02f99b16a6ec82590859f6b26596b6e7c26a3931788a531843e2c4777f249`.
  Tests, Ruff, CodeQL, Documentation, Catalog Check and Auto Release all passed
  on the same merge SHA.
  This release evidence does not authorize a bulk server or worker redeploy.
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

- Current catalog: 16 providers, 14 bandwidth and 2 DePIN.
- Current collectors: 9 shared-registry collectors plus the separate
  account-scoped EarnApp collector.
- Current catalog metadata still contains 15 runtime-capable entries for
  historical compatibility; the one manual-only entry remains explicit. NKN
  direct slots stay outside the generic Docker queue. EarnApp also stays out of
  that queue: VN residential proxies use dedicated MacOS/iOS Docker lanes,
  while non-VN residential proxies use official Ubuntu x64/LXD; generic/raw
  Docker paths remain blocked.
- Fifteen provider runtimes are `PROTECTED_DONE`; EarnApp is separately
  `FOCUS_EARNAPP_MULTIPLATFORM` / `platform_restricted`. Its Account Pool, collector
  and historical evidence remain available.
- Mysterium remains direct-only. Its wallet inventory, lease, identity,
  WireGuard/TUN and runtime contracts are not altered by this branch.

## EarnApp Proxy Pool and runtime baseline (historical runtime contract)

- EarnApp retains catalog/runtime metadata and an active collector lane. The
  qualification and lease rules below apply to the dedicated Ubuntu LXD route;
  no Mac/iOS or generic Docker runtime lease is authorized.
- Only the latest EarnApp WSS verdict `CID_SET` is eligible. `BLACKLIST` is
  blocked, `DECLINE` is quality-rejected, and timeout/transport failures remain
  unknown. WSS ping payloads are returned as binary pong frames without UTF-8
  coercion.
- Country evidence comes from `ipwho.is`; quality flags and IP type come from
  `ipapi.is`. The dashboard shows country/source, IP type/source, generic live
  state, UDP evidence, generic latency, EarnApp verdict/reason/latency and last
  check time without exposing proxy credentials.
- Duplicate egress rows remain available as raw import evidence, but only one
  canonical endpoint can receive a new assignment or scoped lease. Existing
  assignments are not revoked merely because duplicate detection discovers a
  collision.
- EarnApp uses a scoped lease keyed by provider, worker and instance, separate
  from the legacy worker-level proxy assignment. Proxy eligibility for other
  providers is unchanged except that every new lease rejects an egress already
  in active use.
- Duplicate export is masked by default. Raw credential export is owner-only
  and requires an explicit operator action; stored import evidence remains
  encrypted at rest.
- `Delete all proxy pool` is intentionally absolute: after two UI confirmations
  and two exact API confirmation values it deletes all endpoints, worker proxy
  assignment rows, scoped leases, masks, probe evidence and import records.
  Provider configuration and provider-instance rows remain, with their proxy
  references cleared by foreign keys.
- Protected provider catalog/runtime/collector files are outside PRs #27-#29.
  No provider marked `PROTECTED_DONE` was redesigned, redeployed or used as a
  canary by this work.
- The final pre-PR audit corrected two isolated Proxy Pool edge cases: duplicate
  canonicalization now prefers the latest EarnApp `CID_SET` evidence rather
  than any historical/generic eligible probe, and partial geo/type metadata is
  retried instead of being treated as a complete seven-day cache hit.
- Final PR #29 verification passed `1679 passed, 8 skipped` for the full
  non-live suite and `182 passed` for the focused proxy/UI suite. Ruff check,
  changed-file format check, Python compileall, `mkdocs build --strict`,
  `git diff --check`, protected-path comparison and added-line secret-pattern
  checks all passed.

## v1.7.2 Proxy Pool live closeout (2026-08-24)

- PR #27 merged as `94a68a0` and released the qualification baseline as
  `v1.7.0`. PR #28 merged as `2440322` and released the persisted-egress
  intelligence fix as `v1.7.1`. PR #29 merged as `bd8d957` and Auto Release run
  `32748192052` published `v1.7.2` after CI, both image builds, tag resolution
  and embedded-version verification passed.
- Release `v1.7.2` UI digest is
  `sha256:f05069653b725347b3ab115308a2e9a83094c4d8649cb09360ffdea464c44838`;
  worker digest is
  `sha256:c27eb4e98ebee30d5bd4fae27656365f47573958703de4fe139f3b5a022d2ce3`.
  Only the UI image was deployed. The live worker was not pulled, recreated or
  restarted.
- Live `cashpilot-ui` container `101fb16648f1` is healthy on the exact UI
  digest and reports `CASHPILOT_VERSION=1.7.2`. SQLite remains schema `18` with
  `integrity_check=ok`; authenticated `GET /api/proxy-pool`, `GET
  /api/proxy-pool/scheduler`, `GET /api/workers` and `GET /api/fleet/summary`
  all returned HTTP 200.
- `cashpilot-worker` remained container `60b180133540`, local image
  `cashpilot-worker-local:proxy-egress`, image ID `sha256:3eb671780df3`, start
  time `2026-08-20T09:04:41Z`, restart count `0`, and healthy state before and
  after the UI-only deployment.
- Generic Proxy Pool evidence remains authoritative: endpoint `8931` is alive
  at egress `14.180.201.10`, country `Viet Nam`, IP type `residential`, and is
  the canonical row for its egress. Duplicate reconciliation remains `417`;
  scheduler policy remains `enabled=true`, interval `60` minutes, concurrency
  `64`.
- The isolated EarnApp WSS canary rechecked only endpoint `8931` at concurrency
  `1`. Certificate verification no longer failed after PR #29; the authoritative
  result was `WSS_FAIL`, eligibility `unknown`, reason `WSS handshake rejected:
  HTTP/1.1 302 Moved Temporarily`, latency `528 ms`. Because it was not
  `CID_SET`/eligible, no provider-scoped lease or EarnApp container was created.
- Post-canary invariants show zero active and zero historical provider-scoped
  leases, worker `3113` still assigned to proxy `5810`, all three workers online,
  unchanged provider-instance and MYST/NKN wallet-state counts, and zero Grass
  instances. No protected provider, credential, wallet, worker assignment or
  provider runtime was mutated.

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
- Current source status: PRs #17-#19, #21-#25 and releases through `v1.6.3`
  are green. The guarded LXD adoption timeout remains 900 seconds while normal
  deploy timeout remains 60 seconds. The latest full suite passed `1642 passed,
  8 skipped`; NKN-focused tests passed `305 passed, 1 skipped`. Runtime,
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
- PR #24 merged the shared-cache/DNS implementation as `bb52dea` and release
  `v1.6.2` published both images. The isolated `test-us` worker still runs the
  earlier `v1.6.1` image digest
  `sha256:58b8a452e4566a578de224df20d621bc18d1b2739d1eb43d69e9099f02416974`;
  the `v1.6.2` release image digests were UI
  `sha256:7993a5a519c4a42e21a32c78836057658b052af33bb803587d1ae9c51d74ac9e`
  and worker
  `sha256:4909468c68b1d5c7b186b0596e966f3f28db4325588725e2162ee0f09db90f03`.
  The host helper was installed directly from reviewed source for the canary.
  The `v1.6.3` closeout below supersedes only that helper installation. The
  worker image remains an explicit mixed deployment state, not a failed release.

## v1.6.3 NKN host-helper live closeout (2026-08-24)

- PR #25 merged as `f5ee981` and release `v1.6.3` completed on the same SHA.
  The live deployment downloaded the official GitHub tag archive and verified
  every installed helper input by SHA-256 before running
  `scripts/install-nkn-host-helper.sh`.
- The installer updated only the restricted NKN helper files and restarted only
  `cashpilot-nkn-agent.service`. It did not restart or recreate the CashPilot
  worker, the LXD instance, the inner NKN container, a wallet lease or a data
  volume. The helper is enabled and active, has `NRestarts=0`, and its Unix
  socket responds according to the restricted endpoint contract.
- The `test-us` worker container remained
  `308579e2618da1be5e804c4aa8a47e0edc51ee7a38a13ae83242734edee1d0a9`
  on the existing `v1.6.1` worker digest with restart count `0` and unchanged
  start time. No worker image redeploy was required for this host-only change.
- The NKN LXD instance remained running with the same PID, `1 CPU / 1024 MiB`
  hard limits, `boot.autostart=true`, per-slot TCP/UDP forwarding and read-only
  shared-cache device. Inner container ID
  `a3087def4b899c710ef00a5c286b4eff546c7117d0dd55db549dcd60c86840ff`
  remained unchanged with restart count `0` and `restart: always`.
- The post-deploy RPC returned `PERSIST_FINISHED` at height `9690031` with the
  same Node ID
  `c36ecaa9abdcec725d889ec222834f5a1705065ede7f5857cfb56f1d5ee293d7`.
  Wallet, password and config hashes remained unchanged; the wallet and config
  hashes are respectively
  `035cfdd43ee4c6bbf5f0d460b7eb5b8f3985ca05e1ee5bab2c36043dc6e076ca`
  and
  `f75113b8edcf4c4382968c2fac963b3b1f86bb72fc1234c584c921b407b4c965`.
- The shared archive retained inode `325123`, size `5,795,325,602`, mtime and
  SHA-256
  `9c8d29068fd741dab315d17d3c9f3fcdcfe0c389a29fefede7ba06cfd18e10e5`;
  no `.partial` file appeared. Public egress remained `104.211.53.252`.
- Authenticated, read-only `GET /api/workers` and `GET /api/fleet/summary`
  snapshots returned HTTP 200 without rendering credentials. Worker `3098` was
  online with confirmed enrollment and reported the same NKN Node ID as
  `running=true`, `online=true`, `rpc_reachable=true`, backend `lxd` and
  `PERSIST_FINISHED`. Fleet reported two NKN nodes, two online and zero offline.
- This closeout did not mutate `test-sing`, the publisher, R2, either NKN wallet
  lease or any other provider. NKN remains `PROTECTED_DONE`; future work must
  treat its runtime, identities, leases, volumes and ChainDB flow as protected
  baseline unless an explicitly approved defect requires a scoped change.

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

EarnApp is `FOCUS_EARNAPP_MULTIPLATFORM` / `platform_restricted`. VN residential
proxies may deploy through dedicated validated MacOS/iOS Docker lanes; non-VN
residential proxies use official Linux x64 through the dedicated Ubuntu Docker
route. Generic/raw Docker remains blocked. The historical Apple runtime baseline
and existing nodes remain protected. Account collection, token refresh,
historical snapshots and read-only inspection stay available.

## Verification status

- PR #48 merged at `ba2d29d`; Catalog Check, CodeQL, Lint, Tests and Auto
  Release all passed. Release `v1.13.2`, both registry digests, scoped UI/worker
  health, schema `21`, database integrity, preserved worker identity, two fresh
  heartbeats, Fleet `1/0` and Chrome profile 40 remote-device evidence are
  recorded in the current section at the top of this file.
- PR #34 is merged at `a3d2dce`; Auto Release run `32817037347` completed
  successfully and published `v1.8.1`. Fresh authenticated proof confirms the
  dashboard session is masked, the UI-only deployment boundary is intact, DB
  integrity/schema is `ok / 18`, and the full 3,223-row Proxy Pool read model is
  available over 33 bounded pages with zero active leases.
- PRs #27-#29 are merged. Auto Release run `32748192052` completed successfully
  and published `v1.7.2`; both release image manifests resolved and reported
  embedded version `1.7.2` before the tag and GitHub Release were created.
- Fresh live evidence proves the `v1.7.2` UI-only deployment boundary, schema
  `18` integrity, all four authenticated read endpoints, Location/IP Type
  metadata, duplicate reconciliation, scheduler policy, EarnApp WSS result and
  zero scoped-lease residue. The worker ID/image/start time/restart count and
  worker-level assignment `3113 -> 5810` remained unchanged.
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
- Historical technical closeout evidence remains valid: restart/network-
  namespace persistence and two isolated proxy rotations passed on
  `earnapp-recovery-test-sing-2`, while `earnapp-canary-test-sing-1` remained
  unchanged. This does not override the current hosted-runtime compliance gate.
