# Production Resume Checkpoint - 2026-09-14

## Completed in this checkpoint

- Removed the temporary credential-bearing sidecar artifact from the workspace.
- Added an Ubuntu EarnApp fail-closed network contract test: direct fallback, public DNS, and IPv6 egress are rejected.
- Added provider-rotation regression coverage and enforcement:
  - provider masks block replacement candidates in the same provider scope;
  - EarnApp rotation requires the latest eligible `earnapp_wss` probe and residential metadata.
- Read-only Chrome profile 40 audit reached the authenticated CashPilot Settings, Proxy Pool, and Dashboard pages. Text evidence is stored in the adjacent `ui-ux-browser-sweep-2026-09-14-*.txt` files.

## Verification

- EarnApp contract suite: `208 passed, 2 skipped`.
- Provider rotation focused suite: `4 passed`.
- Ruff and `git diff --check`: passed.
- No live provider node was deleted, recreated, rotated, or redeployed.
- Release `v1.50.11` was published after PR #358. The five worker compose files
  initially pinned `cashpilot-worker:1.50.10`. The compose references were
  updated in place, then each worker was pulled and recreated sequentially.
  All five now run `v1.50.11`, are healthy, and retain their existing restart
  policies. Provider containers and data volumes were not touched.
- Post-rollout verification: server, test-US, test-Sing, East Asia, and Japan
  East all report `cashpilot-worker:1.50.11`, `healthy`, restart count `0`, and
  their pre-existing restart policy (`unless-stopped` on server, `always` on
  workers).
- Test-Sing legacy Ubuntu inspection is conclusive: the old bridge runtime is
  `cashpilot/earnapp-ubuntu:asset-d4bb6a003d0f`, has no sidecar, has
  `OUTPUT ACCEPT`, and exposes public resolvers in `/etc/resolv.conf`. Its
  identity volume remains attached. This is a controlled remediation blocker,
  not a reason to mutate it blindly.

## Findings still open

- Legacy Ubuntu EarnApp bridge node `earnapp-prod-ubuntu-20260901-01` lacks the canonical fail-closed firewall/DNS contract and needs deployment-spec/image provenance review before controlled remediation.
- Generic release/rotate concurrency and recovery-hold capacity semantics need dedicated race/counter tests.
- Full provider-wide packet/reboot leak matrix remains unverified; EarnApp evidence cannot be generalized to other providers.
- Authenticated browser screenshots/CDP capture is unavailable in this session; text audit is evidence, not a complete visual sweep.
- Worker earnings import accepts any finite numeric balance; a compromised confirmed worker could distort earnings history. This is a medium business-integrity hardening item, not a claimed exploit without worker compromise evidence.

Production status remains `pending` until the remaining live gates have redacted authoritative evidence.
