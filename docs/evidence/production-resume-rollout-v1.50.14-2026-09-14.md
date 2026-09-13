# Production resume rollout - v1.50.14

Date: 2026-09-14

## Release

- PR #363 merged after Tests, Lint, CodeQL, Catalog Check, and Documentation passed.
- Release workflow completed successfully and published `v1.50.14`.

## Worker/UI rollout

- CashPilot server UI and worker: `ghcr.io/assetforgeai-tech/cashpilot:*:1.50.14`, healthy, restart count `0`, existing `unless-stopped` policy.
- Test-US worker: `ghcr.io/assetforgeai-tech/cashpilot-worker:1.50.14`, healthy, restart count `0`, existing `always` policy.
- Test-Sing worker: `ghcr.io/assetforgeai-tech/cashpilot-worker:1.50.13`, healthy, restart count `0`, existing `always` policy.
- Azure East Asia and Japan East workers: `ghcr.io/assetforgeai-tech/cashpilot-worker:1.50.14`, healthy, restart count `0`, existing `always` policy.

Only CashPilot control-plane containers were recreated. Provider containers, node identities, proxy leases, and provider data volumes were not mutated.

## Drift found and corrected

The server and test-US had legacy Compose files whose image pins differed from the deployed release. The server was corrected to the authoritative `1.50.14` GHCR images. Test-US was corrected through its worker Compose file. Azure Compose resolution was checked explicitly because the repository contains a stale UI compose file; worker Compose now resolves to `1.50.14`.

## Remaining gates

- Test-Sing legacy EarnApp bridge still requires a controlled fail-closed network remediation after preserving identity/account/proxy evidence.
- Provider-wide DNS/IPv6/UDP/DoH/DoT/process-bypass matrix remains open.
- Full authenticated visual browser sweep remains open because CDP screenshots are unavailable.
- Earnings-import integrity hardening remains open pending the bounded-source patch.
