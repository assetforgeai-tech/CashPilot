# Provider topology code verification — 2026-09-13

## Scope

- Direct-only, proxy-only, and hybrid lane policy.
- Lane-scoped lifecycle decisions.
- Usage-stall restart behavior.
- Direct-route and provider/account failure isolation.

## Evidence

- Local suite: `2973 passed, 8 skipped`.
- Focused topology/lifecycle/network/UI suite: `197 passed`.
- Ruff and format checks: passed.
- `git diff --check`: passed.
- PR #316 head `c30305f2`: CodeQL, strict build, Ruff, and test checks passed.
- Live workers `20.187.79.110` and `20.210.93.220`: worker image `ghcr.io/assetforgeai-tech/cashpilot-worker:1.40`, health 200, restart policy `always`.

## Current boundary

The live workers currently report zero provider containers. The CashPilot server still runs UI/worker image `1.37`; live provider canaries must wait for the approved release and server deployment. No provider was deployed blindly.

## Policy now enforced

- Direct route failure is `blocked`; no proxy fallback.
- Provider authentication failure or account suspension is `observe`; no unrelated runtime mutation.
- Confirmed usage stall restarts the same lane and preserves identity/lease.
- Verified proxy failure rotates only the proxy lane.
