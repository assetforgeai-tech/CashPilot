# Azure production-resume checkpoint

## Recheck after release v1.50.20

- Auto Release run `34807714648` completed successfully; release `v1.50.20`
  is published.
- Both scoped Azure workers were upgraded to
  `ghcr.io/assetforgeai-tech/cashpilot-worker:1.50.20`.
- East Asia and Japan East report `running|healthy` with Docker
  `restart=always`.
- The upgrade preserved `/data`, public-slot storage, worker identity/key, and
  existing provider container IDs.
- Repository verification after the rollout: `3082 passed, 10 skipped` and
  Ruff clean.
- EarnApp remains unverified: the three required private runtime images cannot
  be pulled with the currently available GHCR credential (`denied`). No
  EarnApp container was created on either Azure worker.

## GHCR credential recheck

- A newly supplied GHCR credential authenticated successfully on both scoped
  Azure workers.
- All three private `20260912-production-candidate` images pulled successfully
  on both workers.
- Local asset tags were applied without starting containers:
  `cashpilot/earnapp-mac-canary:asset-02dc8060a352`,
  `cashpilot/earnapp-ios:asset-28b1be5d6668`, and
  `cashpilot/earnapp-ubuntu:asset-72e54b17fb3a`.
- Verified image IDs match on both workers: macOS
  `sha256:45c62c73242a281f5e293a6249bae4706b3c2ff8f9ec23a01b3a01a7a879170d`,
  iOS `sha256:f7ca70ce9ef7bd72321bafa8be3f00047ceb056e67221ac93c10394592049930`,
  Ubuntu `sha256:70265ba720c27bb9398f97432fd9e151f841aedf679c1f82831080ac9d0109e3`.
- No EarnApp node was created in this step; provider canary remains pending
  owner-authorized deployment and dashboard/earnings verification.

- Scope: the two new Azure workers only. Historical test workers are excluded.
- Release `v1.50.20` passed CI and was published after PR #370.
- Both Azure workers run `v1.50.20` and report healthy. The UI container is
  intentionally outside this worker-only rollout.
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
