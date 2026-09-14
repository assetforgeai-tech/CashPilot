# Azure production-resume checkpoint

- Scope: the two new Azure workers only. Historical test workers are excluded.
- Release `v1.50.19` passed CI and was published after PR #369.
- CashPilot UI and both Azure workers run `v1.50.19` and report healthy.
- Worker data, public-slot volumes, worker identities, and existing provider
  containers were preserved during the worker rollout.
- Fresh EarnApp deployment is not verified. The worker fail-closed response
  identifies the missing local image `cashpilot/earnapp-ios:asset-28b1be5d6668`.
  The same dedicated lane requires the corresponding macOS and Ubuntu images.
- Preloading is currently blocked by GHCR authorization: the supplied package
  credential receives `denied` for private package pulls, and the active GitHub
  token lacks `read:packages`.
- No EarnApp node was created on Azure after the failed attempt; no historical
  test worker was mutated.

Production-ready remains unclaimed until a fresh Azure node is mapped to the
provider dashboard and shows an authenticated usage/earnings delta.
