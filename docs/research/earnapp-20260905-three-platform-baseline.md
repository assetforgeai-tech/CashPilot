# EarnApp three-platform baseline (2026-09-05)

This is a read-only forensic baseline from the authoritative test VPS. The
source containers were not stopped, recreated, linked, rotated, or modified.
Encrypted identity profiles, cookies, tokens, proxy credentials, and identity
volumes are intentionally excluded.

| Lane | Device | Observed image/client | Archive SHA-256 | Evidence scope |
| --- | --- | --- | --- | --- |
| MacOS | `sdk-mac-854c0d0a36f662bb1ecee7a6feaf4739` | `sha256:c42b5055e60102f57cb226c9d68194b4bb34e07dd94b37969ce262febd92b018`, `1.605.415` | `416349b5556c124021af2cd2fb674b55a9c614a9319c7383b21c24b1fe26a723` | WSS, registration, heartbeat, changing runtime activity |
| iOS | `sdk-ios-4f788757ca191fbc90a2e73ff8795eee` | `sha256:414852921fab883f6a417b18fe4dc520d53f9fd6da39f0347f64aed4f1b9fd10`, `1.617.813` | `9f6345b0bd97e5732fc643ee85092e40b311c9bed88cf370c1d89d71979b89c6` | egress, iPhone identity, registration URL, WSS and runtime activity |
| Ubuntu | `sdk-node-5ade4ff405c249038304ccec4d981665` | `sha256:19b8d5831f0e83c0beb9a514bc9ed40c0be252ac101217fc01a6e2ac4714c559`, `1.665.73` | `103ad18352f4ce313096300d8e148925ba38dce11573fb0f77b4d8bd068d8b95` | watchdog, proxy/registration retry; capture-time egress failure |

## Integration rules

- MacOS and iOS images are host-bound forensic captures. Their `BOUND_FP_*`
  values and source identity volumes must not be promoted as generic images.
- Ubuntu is pinned to the private immutable image
  `ghcr.io/assetforgeai-tech/cashpilot-earnapp-ubuntu@sha256:19b8d5831f0e83c0beb9a514bc9ed40c0be252ac101217fc01a6e2ac4714c559`.
- The Ubuntu source entrypoint is pinned by SHA-256
  `b03e12ed092f8386177910b9d9d89e6189c66730472a891d67192a958a4344bc`.
- The captured route is TCP through redsocks/iptables. It does not prove
  absolute UDP, DNS, WebRTC, or host-kernel concealment.
- `NODE_TLS_REJECT_UNAUTHORIZED=0` was observed in source images and remains a
  canary exception; it is not a default security recommendation.

This document records evidence and constraints only. Live deployment requires
an impact map, separate canary identities/proxies, and fresh online plus
positive-usage and restart-persistence evidence.
