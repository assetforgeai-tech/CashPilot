# PayPal Pool UI rollout - 2026-09-11

## Change

- Moved the PayPal Pool controls to the top of the EarnApp Account Pool settings section.
- The destination input and `Add PayPal` action are visible before the account inventory and recovery table.
- Existing fixed assignment and quarantine policy is unchanged.

## Verification

- PR #250 merged at `ecf3c208d2d50e6fe11def3fb78cec89870bcad8`.
- Tests, Ruff, and CodeQL passed on the PR.
- Auto Release completed and published `v1.32.3`.
- Server `cashpilot-ui` runs `ghcr.io/assetforgeai-tech/cashpilot:1.32.3`, healthy, restart count `0`.
- Server `cashpilot-worker` retained its container ID, image `1.32.0`, health, and restart count `0`.
- Live template contains the PayPal input and places the pool before the account grid.
- Live database: SQLite integrity `ok`, foreign-key errors `0`.

## Remaining gates

- Chrome profile 40 interactive UI sweep remains unavailable because no approved CDP/connector is exposed.
- Live token auto-import and PayPal external mutation tests remain unverified.
- Provider-wide packet-capture/reboot leak evidence remains incomplete.
