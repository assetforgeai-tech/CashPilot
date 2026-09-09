# EarnApp canary reboot evidence (2026-09-09)

## Additional macOS non-VN canary

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

The VPS rebooted cleanly. Docker returned active, all six target containers auto-started, and the worker heartbeat returned `online` with version `1.23.4`. Post-reboot UUIDs remained:

- `sdk-mac-5a73bd21747433703f51a20a96d75230`
- `sdk-mac-ce6f3d6ba4c1905a73728069f3a9f1ff`
- `sdk-ios-4416b34ca1be9d5dd809ba617a8f32a1`
- `sdk-ios-9fcb4b9bc83679c4b367a51f285050db`
- `sdk-node-cdaa3e82671e4283b5c87ec5bf7ee6b9`
- `sdk-node-1be443257d284827b0f874966ce3cbcd`

Worker provider state after reboot reported `EarnApp online=9, offline=0` across its active fleet. Account collector snapshots remained reachable: account `2` reported `7/6` online/offline and account `470` reported `6/4`; these account totals include nodes outside this six-node canary and are not proof of positive usage for every target node.

Positive usage for the two new non-VN macOS nodes remains an open EarnApp dashboard observation gate; no further recreate or proxy rotation is justified while their route and identity remain healthy.
