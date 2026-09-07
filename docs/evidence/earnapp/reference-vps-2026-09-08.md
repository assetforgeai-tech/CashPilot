# EarnApp Reference VPS Inventory

Source: `earnapp_update_05092026/vps.txt` (read-only inventory, 2026-09-08).

## Host

- Host kernel: `Linux 6.17.0-1022-azure`.
- Docker network: bridge, container LAN in `172.17.0.0/16`.
- macOS/iOS: `CAP_NET_ADMIN`, `unless-stopped`, `NanoCpus=1000000000`, `Memory=104857600`, swap `209715200`.
- Ubuntu: `CAP_NET_ADMIN`, `unless-stopped`, `NanoCpus=1000000000`, `Memory=104857600`, swap `209715200`.

## macOS reference

- Upgraded image: `ghcr.io/assetforgeai-tech/cashpilot-earnapp-macos@sha256:3f2a7b9998e6940616c0ec2beec2bfda73e12b598c2da5c80d7ec57ba5178a6d`.

- Entrypoint: `/usr/local/bin/bound-entrypoint` -> fingerprint check -> `earn-supervisor`.
- Main script hash: `111056c55165df8cdaeb00af0ada98c1e724c7c5f990e925b1132cbc58d60645`.
- Bound entrypoint hash: `e05a63a8b030b2afd150d67b007b1ade8aa5c2ece6a4d41e7a8ad4babf5c7453`.
- Binary hash: `3333e8dd1e1a5433d79542ad646edcf07256e3f9fee05e14735e61e606a374d0`.
- Uses encrypted per-node profile, host fingerprint mounts, watchdog, redsocks/iptables route, persisted machine-id and hostname.

## iOS reference

- Upgraded image: `ghcr.io/assetforgeai-tech/cashpilot-earnapp-ios@sha256:915875703413a2192c0995bbfc3af4921ed26755a8fe43d329d6f3ebc7d9e0bb`.

- Entrypoint: `/usr/local/bin/bound-entrypoint` -> fingerprint check -> `earn-supervisor`.
- Bound entrypoint hash: `e05a63a8b030b2afd150d67b007b1ade8aa5c2ece6a4d41e7a8ad4babf5c7453`.
- Main script hash: `802b5c305bc552bb06d2e9cbfaa00297d1da3a1ac9f58a173cceb2d8b79fa001`.
- Binary hash: `cec01fee62c3969fa10d1ced803432f1e88074b505cb8477cc00b11f61fa5e88`.
- Uses the same host fingerprint/proxy/watchdog layer; iOS identity metadata remains profile-specific.

## Ubuntu reference

- Upgraded image: `ghcr.io/assetforgeai-tech/cashpilot-earnapp-ubuntu@sha256:3e63d79166d493c55879635071c85da298e0d7c13f186dedcb579f9512abdc41`.

- Entrypoint: `/usr/local/bin/entrypoint.sh`.
- Main script hash: `b03e12ed092f8386177910b9d9d89e6189c66730472a891d67192a958a4344bc`.
- Host helper hash: `52b3eb7cdf1edbd18bb79f1f643529b7be2b66eaf3e591f3c72e325bcd457ede`.
- Uses `earnapp-host ensure/apply`, redsocks/iptables, proxy DNS/egress checks, install-device retry, watchdog, exponential backoff and proxy-failure escalation.
- The upgraded image digests above are authoritative only for this canary source; production promotion still requires GHCR ownership and supply-chain verification.
- The reference Mac/iOS images explicitly set `NODE_TLS_REJECT_UNAUTHORIZED=0`; the derived canary preserves this for behavioral fidelity. Treat it as an EarnApp-only risk and do not propagate it to other providers.

## Normalization decisions

- Copy behavior and contracts, not node UUIDs, account data, proxy credentials, volumes or host fingerprint values.
- Preserve LAN/interface mapping and proxy bypass rules exactly where they are part of the EarnApp protocol.
- Keep TLS verification enabled by default in CashPilot; reference `NODE_TLS_REJECT_UNAUTHORIZED=0` requires a separate evidence-backed decision.
- Kernel spoofing is not guaranteed by Docker; verify each field and report unavoidable host-kernel exposure.
