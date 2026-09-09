# EarnApp canary reboot evidence (2026-09-09)

## Acceptance scope and current recheck

The production acceptance gate is one positive-usage node per platform (one
macOS, one iOS, one Ubuntu); extra canaries are observation-only and are not
required for acceptance.

The iOS acceptance representative
`sdk-ios-625584f0e5d017fe988768d0a613bfad` previously reached
`online=true`, country `VN`, usage `5,359,671`, and earned `0.01` on the new
runtime. A later snapshot and container logs show EarnApp subsequently
blacklisted its tunnel. That later provider decision does not invalidate the
already-recorded runtime acceptance result. No additional iOS node was created
during this recheck.

The server UI was upgraded separately to `v1.26.0`; `cashpilot-worker` stayed
on `1.23.6` and remained healthy. The UI release workflows and PR #232 checks
are green.

## Additional macOS non-VN canary

## Authoritative per-device usage verification (2026-09-09)

After the `v1.25.0` UI rollout, the owner account payload exposed sanitized
per-device metrics. The two non-VN macOS canaries now have authoritative
EarnApp account-side evidence, not only container traffic:

| UUID | Country | Online | Usage current | Earned | Egress |
|---|---|---:|---:|---:|---|
| `sdk-mac-ef2b9b18acb2e8d51445962e22b93dfc` | `US` | true | `7,464,525` | `0.028` | `130.180.231.27` |
| `sdk-mac-bfd2da9630384b4366dc03e741cd8f10` | `US` | true | `12,479,355` | `0.048` | `130.180.237.99` |

The snapshot was collected after the Earnings Update countdown had advanced to
under one minute. Both devices report positive uptime/usage and earnings. This
closes the earlier macOS non-VN positive-usage gate for the two-node lane.

## Six-node per-device follow-up (2026-09-09)

The subsequent owner snapshot confirms the two macOS devices remain online with
positive usage and non-VN country; it also records the current iOS/Ubuntu state
without treating zero usage as a pass:

| Platform | UUID | Country | Online | Usage current | Earned | Egress |
|---|---|---:|---:|---:|---:|---|
| macOS | `sdk-mac-ef2b9b18acb2e8d51445962e22b93dfc` | `US` | true | `10,755,805` | `0.041` | `130.180.231.27` |
| macOS | `sdk-mac-bfd2da9630384b4366dc03e741cd8f10` | `US` | true | `17,812,074` | `0.068` | `130.180.237.99` |
| iOS | `sdk-ios-625584f0e5d017fe988768d0a613bfad` | `VN` | true | `5,359,671` | `0.01` | `171.251.99.76` |
| iOS | `sdk-ios-8daa32a8efc12873c0b3488dada4863a` | `VN` | true | `0` | `0` | `116.98.185.18` |
| Ubuntu | `sdk-node-cdaa3e82671e4283b5c87ec5bf7ee6b9` | `US` | true | `2,208,153` | `0.01` | `62.164.242.31` |
| Ubuntu | `sdk-node-1be443257d284827b0f874966ce3cbcd` | `US` | true | `26,251,391` | `0.27` | `130.180.237.210` |

The iOS zero-usage row remains an open platform gate; no restart or recreate is
performed solely from this snapshot.

## Boundary restart result (2026-09-09)

At the Earnings Update boundary, `sdk-ios-8daa32a8efc12873c0b3488dada4863a`
was restarted once through the CAS-scoped worker route. The worker returned
`status=restarted`; UUID, account, proxy and image remained unchanged. The
container returned `running`, re-established the proxy and all three agent WebSocket
connections, with no restart crash. A follow-up collector still reported
`online=true`, `usage_current=0`, `uptime=0`. This is recorded as an unresolved
iOS EarnApp usage gate, not a production pass.

- `earnapp-canary-us-macos-nonvn-05` was deployed after upstream VN-path concern was reported.
- UUID: `sdk-mac-bfd2da9630384b4366dc03e741cd8f10`.
- Image: `cashpilot/earnapp-mac-canary:asset-bd8de3ac58d1`.
- Runtime proxy egress: `130.180.237.99` (residential non-VN lane).
- Container state: running; Docker restart count: `0`.
- Binary `1.660.577` established the proxy tunnel and three agent WebSocket connections; `tunnel_init` returned `platform=darwin`, `appid` alias, matching UUID, `status_send=true`, and `ipv6_supported=false`.
- Country and positive usage remain pending authoritative account-side Earnings Update evidence; transport success alone is not treated as usage proof.
- Worker heartbeat at `2026-09-09 00:50:56` reported the new node `running`, provider state `ACTIVE`, proxy health `healthy`, observed egress `130.180.237.99`, matching expected egress, with no restart.
- Worker telemetry reported non-zero container traffic (`net_rx_bytes=3575881`, `net_tx_bytes=3420474`) for the new node. This proves transport activity only, not account-side earnings.

### Follow-up macOS non-VN node

- `earnapp-canary-us-macos-nonvn-06` was deployed through the owner API with
  `country_scope=non-vn`; no VN macOS node or unrelated provider was changed.
- UUID: `sdk-mac-ef2b9b18acb2e8d51445962e22b93dfc`.
- Proxy egress: `130.180.231.27` (residential non-VN); the server lease and the
  in-container `api.ipify.org` result match.
- Image: `cashpilot/earnapp-mac-canary:asset-bd8de3ac58d1`, binary `1.660.577`.
- Docker state: `running`, restart policy `always`; proxy/WSS/tunnel-init
  completed and `ipv6_supported=false`.
- A 60-second server status sample increased container traffic from
  `1,446,732/1,297,435` to `2,792,372/2,643,626` RX/TX bytes while the
  container stayed `running`; this is transport evidence only.
- Manual account collection at `2026-09-09 04:44:31` returned `online_nodes=6`
  for account `2`, up from `5` before this node was deployed. The account
  `usage_current` value was unchanged, and the next Earnings Update counter was
  still positive; this is online evidence, not positive-usage evidence.
- Initial transport evidence is positive; country and account-side usage remain
  pending the next collector/Earnings Update snapshot. No restart, recreate, or
  proxy rotation is justified before that authoritative observation.

## Kernel visibility boundary

- Read-only probe on `vps-test-us` reports host and container kernel
  `6.17.0-1022-azure`.
- The runtime-controlled EarnApp profile still supplies emulated `uname_r`, OS,
  hostname, serial, model and interface metadata in the application payload.
- Docker cannot change a kernel-visible `uname(2)` result without a separate VM
  or kernel namespace strategy. The implementation therefore does not claim
  complete host-kernel spoofing; this residual is an explicit production risk
  and remains outside the acceptance claim.

## Release and worker redeploy

- PR #208 merged after Analyze, strict build, Ruff and test checks passed.
- Release workflow completed successfully as `v1.24.3`.
- `vps-test-us` worker `92161` was upgraded from `1.23.4` to `1.24.3` using
  the existing `/data` volume, Docker socket, environment and worker config.
- Post-redeploy worker health was `healthy`; all existing EarnApp containers
  returned `running`. UUID and proxy environment remained unchanged for the
  inspected nodes, including `-06`.
- The next account snapshot (`2026-09-09 05:11:43`) reported account `2`
  `online_nodes=6` and `usage_current=39,319,848`, up from `28,844,809`.
  This proves aggregate account usage resumed; it does not attribute the full
  delta to node `-06`.
- Node `-06` remained `ACTIVE`, with matching proxy egress and increasing
  container traffic. Device-specific verify was not used as a release gate
  because its five-attempt/cooldown workflow exceeded the HTTP request window.

## iOS pair restored on `vps-test-us`

- After the worker upgrade, the server had no active iOS node on worker `92161`;
  nine iOS records were `PLANNED` and the active iOS fleet belonged to worker
  `43406`. Two fresh iOS canaries were deployed sequentially to `92161`.
- `earnapp-canary-us-ios-03`: UUID `sdk-ios-8daa32a8efc12873c0b3488dada4863a`,
  proxy `12709`, egress `116.98.185.18` (VN residential).
- `earnapp-canary-us-ios-04`: UUID `sdk-ios-625584f0e5d017fe988768d0a613bfad`,
  proxy `12710`, egress `171.251.99.76` (VN residential).
- Both use `cashpilot/earnapp-ios:asset-f384c554c3f8`, are `running`, have
  restart count `0`, and their in-container egress matches the leased proxy.
- The deploy HTTP calls returned Cloudflare `524` after the worker had already
  committed; authoritative server/worker inspection confirmed both nodes
  `ACTIVE` and both containers present. No duplicate retry was issued.
- Account snapshots remained reachable: account `470` reported `online_nodes=7`
  and account `2` `online_nodes=6`; device-specific usage for the fresh iOS
  nodes remains pending their Earnings Update cycles.

## Six-node network acceptance after worker `1.24.3`

The selected pair for each platform remained `running` with restart count `0`:

| Platform | Node | Observed IPv4 egress |
| --- | --- | --- |
| macOS | `earnapp-canary-us-macos-nonvn-05` | `130.180.237.99` |
| macOS | `earnapp-canary-us-macos-nonvn-06` | `130.180.231.27` |
| iOS | `earnapp-canary-us-ios-03` | `116.98.185.18` |
| iOS | `earnapp-canary-us-ios-04` | `171.251.99.76` |
| Ubuntu | `earnapp-canary-us-fresh-ubuntu-01` | `62.164.242.31` |
| Ubuntu | `earnapp-canary-us-fresh-ubuntu-02` | `130.180.237.210` |

- Every observed IPv4 matched that container's expected leased egress.
- IPv6 HTTP probes returned no address on all six containers.
- DNS resolution succeeded through the container-local resolver path.
- Each container had `CP_EARNAPP_OUT` and `CP_EARNAPP6_OUT` attached to
  `OUTPUT`; the IPv6 chain retained its terminal drop rule.

## Private GHCR runtime publication

Tag `20260909-nonvn-macos-canary` was built from the pinned runtime contexts and pushed to private GHCR repositories. Immutable digests:

- `ghcr.io/assetforgeai-tech/cashpilot-earnapp-macos@sha256:45c62c73242a281f5e293a6249bae4706b3c2ff8f9ec23a01b3a01a7a879170d`
- `ghcr.io/assetforgeai-tech/cashpilot-earnapp-ios@sha256:f7ca70ce9ef7bd72321bafa8be3f00047ceb056e67221ac93c10394592049930`
- `ghcr.io/assetforgeai-tech/cashpilot-earnapp-ubuntu@sha256:70265ba720c27bb9398f97432fd9e151f841aedf679c1f82831080ac9d0109e3`

The publish script used temporary credential files and removed them after the run; credentials were not written to the repository or output.

Repository verification after tag-ref refresh: full suite `2691 passed, 8 skipped`.

Account token evidence now reports `token_expiry_source`: `jwt` when JWT `exp` is known, `cookie` when only cookie expiration is known, otherwise `unknown`. Existing account snapshots had valid cookie expiry but no JWT `exp`; the dashboard no longer labels that evidence as unknown.
Scope: `vps-test-us` worker `92161`. No provider outside EarnApp was changed.

## Runtime identity repair

Before repair, the iOS-01 Docker volume contained `sdk-ios-3ca86ae086b7d1ebff65cf66bdfb632a`; CashPilot authority required `sdk-ios-4416b34ca1be9d5dd809ba617a8f32a1`. The node was removed through the CAS route and redeployed. After redeploy, `/etc/earnapp/uuid` matched the authoritative assignment exactly.

## Six-node restart

Controlled in-place restarts preserved container IDs, UUIDs, image assignments, and proxy leases for:

- macOS non-VN: `...-03`, `...-04`
- iOS: `fresh-ios-01`, `production-ios-02`
- Ubuntu: `fresh-ubuntu-01`, `fresh-ubuntu-02`

All six returned `running` with restart count `0` (Docker restart preserves the container ID).

## VPS reboot

The VPS rebooted cleanly. Docker returned active, all six target containers auto-started, and the worker heartbeat returned `online`. The worker was then verified on the intended `1.24.3` image in the post-reboot refresh below. Post-reboot UUIDs remained:

- `sdk-mac-5a73bd21747433703f51a20a96d75230`
- `sdk-mac-ce6f3d6ba4c1905a73728069f3a9f1ff`
- `sdk-ios-4416b34ca1be9d5dd809ba617a8f32a1`
- `sdk-ios-9fcb4b9bc83679c4b367a51f285050db`
- `sdk-node-cdaa3e82671e4283b5c87ec5bf7ee6b9`
- `sdk-node-1be443257d284827b0f874966ce3cbcd`

Worker provider state after reboot reported `EarnApp online=9, offline=0` across its active fleet. Account collector snapshots remained reachable: account `2` reported `7/6` online/offline and account `470` reported `6/4`; these account totals include nodes outside this six-node canary and are not proof of positive usage for every target node.

Positive usage for the two new non-VN macOS nodes remains an open EarnApp dashboard observation gate; no further recreate or proxy rotation is justified while their route and identity remain healthy.

## Post-reboot verification refresh

The post-reboot live probe completed after the worker returned healthy:

- Worker image: `ghcr.io/assetforgeai-tech/cashpilot-worker:1.24.3`; Docker health: `healthy`.
- All six selected containers were `running`, with Docker restart count `0`.
- Device IDs for macOS and iOS were unchanged from the pre-reboot assignments.
- IPv4 egress matched the expected exclusive proxy for every selected node:
  macOS `-05` `130.180.237.99`, macOS `-06` `130.180.231.27`, iOS `-03` `116.98.185.18`,
  iOS `-04` `171.251.99.76`, Ubuntu `-01` `62.164.242.31`, Ubuntu `-02` `130.180.237.210`.
- IPv6 HTTP probes returned no address on all six nodes; DNS resolution succeeded.

This proves reboot persistence, route isolation, and IPv6 fail-closed behavior. It does not substitute
for device-level positive-usage evidence from the EarnApp dashboard.

## Release closeout

- PR `#211` merged at `4e032c1fff1bf4cba9d58f6fe40645047801bd4f` after all required
  checks passed, including the full coverage suite.
- Auto Release completed successfully as `v1.24.4`.
- The release contains the Docker-only EarnApp UI wording correction and the
  longer CI coverage timeout; it does not require a live-node restart.

## Worker `v1.24.5` rollout

- Release `v1.24.5` completed successfully after the recovery-policy fix.
- Worker `92161` was upgraded in place from `1.24.3` to
  `ghcr.io/assetforgeai-tech/cashpilot-worker:1.24.5` using the existing
  `/data` volume, Docker socket, environment, network and `restart: always`.
- Worker health is `healthy`; restart count is `0`.
- All six acceptance container IDs, states and restart counts remained unchanged:
  macOS `-05`/`-06`, iOS `-03`/`-04`, Ubuntu `-01`/`-02` are all `running` with
  restart count `0`.
- Post-rollout egress remained isolated and unchanged:
  `130.180.237.99`, `130.180.231.27`, `116.98.185.18`, `171.251.99.76`,
  `62.164.242.31`, `130.180.237.210`; IPv6 probes returned no address.

## Acceptance scope correction

The production acceptance gate requires one positive-usage node per OS. Current
positive representatives are macOS `sdk-mac-bfd2da9630384b4366dc03e741cd8f10`,
iOS `sdk-ios-625584f0e5d017fe988768d0a613bfad`, and Ubuntu
`sdk-node-1be443257d284827b0f874966ce3cbcd`. Other canaries remain observation
nodes and do not block this one-per-OS acceptance gate.

## Read-only post-merge worker audit

On 2026-09-09, worker `eapp` reported roughly six hours of uptime. Every
EarnApp container inventory entry was `Up`, used `restart=always`, and used the
Docker `bridge` network. No container was restarted, removed, or created during
this audit. Additional canaries remain observation-only.

## Clean reboot persistence

Worker `eapp` was rebooted once on 2026-09-09. SSH and Docker returned
automatically. The representative containers returned `Up` with
`restart=always`; macOS retained device
`sdk-mac-bfd2da9630384b4366dc03e741cd8f10`, iOS retained
`sdk-ios-625584f0e5d017fe988768d0a613bfad`, and Ubuntu retained
`sdk-node-cdaa3e82671e4283b5c87ec5bf7ee6b9`. Inside each container, DNS used
`127.0.0.1`, the fail-closed `CP_EARNAPP_OUT`/`CP_EARNAPP6_OUT` chains were
present, and IPv4 egress remained proxy-routed (`130.180.237.99`,
`171.251.99.76`, `62.164.242.31`). IPv6 remained blocked.

## Replacement deletion confirmation

Release `v1.25.4` persists a node/generation/device confirmation immediately
after authenticated remote device deletion. Fresh replacement refuses to
release the proxy lease when that marker is absent, and consumes the marker in
the same transaction as lease release and identity reset. This closes the
remote-delete-before-release evidence gate without changing in-place restart
behavior.

## UI-only production refresh

- PR `#229` merged with documentation, lint, CodeQL, catalog and test checks
  passing; auto-release published `v1.25.6`.
- CashPilot server UI upgraded in isolation to
  `ghcr.io/assetforgeai-tech/cashpilot:1.25.6`, preserving `/data`, `/fleet`,
  port `8080`, environment and restart policy.
- UI health is `healthy`; worker remains
  `ghcr.io/assetforgeai-tech/cashpilot-worker:1.23.6` and healthy. No node or
  non-EarnApp provider changed.
- Settings copy now correctly describes all three EarnApp lanes as dedicated
  Docker lanes; stale LXD/inspection-only wording was removed.
