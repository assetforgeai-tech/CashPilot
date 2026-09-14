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

## Azure EarnApp canary attempt

- macOS canary `azure-macos-canary-20260914` deployed on worker `118903`;
  iOS canary `azure-ios-canary-20260914` deployed on worker `118904`.
- Both nodes are `ACTIVE`, have one persisted device identity and one healthy
  proxy lease; worker containers are running with the verified asset tags.
- Runtime logs show proxy-mediated external-IP checks, EarnApp device-online,
  proxy-connected, and successful `tunnel_init` responses for the macOS lane.
- The authenticated workload verifier remains `verification_pending` for both
  lanes; no country/usage/earnings claim is made yet.
- Ubuntu canary was not created because the server correctly returned
  `no eligible residential EarnApp proxy available`; no lease or container was
  left behind.
- The first canary exposed the earlier candidate-label mismatch; it was fixed
  by rebuilding from the current manifest and validating labels before deploy.
- Rebuilt local contract-fix images were created independently on both Azure
  workers from the current contexts; their asset labels now match the server
  contract. GHCR push was intentionally not attempted with the read-only PAT.
- The macOS and iOS runtime logs show successful proxy connection, device-online
  state, and tunnel initialization. The account-side workload verifier still
  returns `verification_pending`, so this is not earnings proof.
- Current proxy capacity reports `eligible=289`, `leaseable=279`, `used=9`,
  `occupied=9`; Ubuntu deployment was refused because no policy-eligible
  residential proxy was available at its allocation point.
- The UI was then upgraded to `v1.50.20`; it is `healthy`, SQLite integrity is
  `ok`, and the worker/mount preservation checks passed.
- Latest account snapshots show both active accounts authenticated and reporting
  online nodes, but the new macOS/iOS canaries have not produced an observed
  earnings/usage delta yet. Their one-hour Earnings Update windows are still
  pending; this remains an open production gate.
- Runtime inspection confirms both canary containers are running with restart
  count `0`, expected identity labels, DNS bound to `127.0.0.1`, and the
  `CP_EARNAPP_OUT` fail-closed output chain. This is routing evidence only, not
  proof of provider earnings.

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

## Allocator diagnosis (2026-09-14)

- Current explicit Settings policy enables `macos` and `ios` for `VN`, enables
  all three platforms for `NON_VN`, and explicitly disables Ubuntu for `VN`.
- Fresh proxy-pool evidence reports `289` EarnApp-eligible residential rows;
  all are `VN`, with zero eligible `NON_VN` rows at this check.
- Ubuntu refusal is therefore policy-consistent, not a lease leak or allocator
  crash. No policy override or proxy mutation was performed.
- Ubuntu requires either enabling `earnapp_platform_vn_ubuntu` in Settings or
  obtaining a non-VN residential proxy with latest `CID_SET/eligible` evidence.
