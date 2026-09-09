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

## Private GHCR runtime publication

Tag `20260909-nonvn-macos-canary` was built from the pinned runtime contexts and pushed to private GHCR repositories. Immutable digests:

- `ghcr.io/assetforgeai-tech/cashpilot-earnapp-macos@sha256:45c62c73242a281f5e293a6249bae4706b3c2ff8f9ec23a01b3a01a7a879170d`
- `ghcr.io/assetforgeai-tech/cashpilot-earnapp-ios@sha256:f7ca70ce9ef7bd72321bafa8be3f00047ceb056e67221ac93c10394592049930`
- `ghcr.io/assetforgeai-tech/cashpilot-earnapp-ubuntu@sha256:70265ba720c27bb9398f97432fd9e151f841aedf679c1f82831080ac9d0109e3`

The publish script used temporary credential files and removed them after the run; credentials were not written to the repository or output.
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
