# EarnApp canary reboot evidence (2026-09-09)

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
