# EarnApp macOS Upgrade Evidence Review (2026-09-04)

The source evidence is retained outside the repository at
`earnapp_new_update/earnapp_macos_upgrade_20260904`. This note records the
implementation-relevant conclusions without copying identities, credentials,
profile material, or live addresses.

## Findings

- The upgraded image contains a real SDK/binary change (`1.605.415` to
  `1.660.577`), not only a wrapper change. The native ELF layout is unchanged;
  the changed package content is in the peer client and version/config records.
- The peer client improves local-address/interface handling, filters the full
  Docker bridge range `172.16.0.0/12`, derives the tunnel response alias from
  app ID/platform, and reduces SDK tunnel-decline backoff to a two-hour cap.
- The image entrypoint adds a bounded decline cooldown (60-3600 seconds,
  default 600) to prevent restart storms. This is backoff only; it does not
  bypass provider policy or link a device.
- The evidence does **not** show a new UUID, serial, model, OS fingerprint,
  OAuth/link flow, or proxy-policy bypass. Identity remains profile/state
  responsibility and must stay per-node.
- The observed image used a 100 MiB memory limit and recorded cgroup OOMs
  during install/startup. The limit must not be copied into a broad rollout
  without a canary resource check.

## CashPilot application

These findings are compatible with the existing Docker-only EarnApp runtime:
identity/profile state remains volume-scoped, proxy routing remains fail-closed,
and platform-specific identity fields remain outside the shared image. The SDK
upgrade should be introduced as a canary image/runtime change, with positive
usage and dashboard evidence required before adoption by other platforms.

Automatic lifecycle mutation is separately gated by the CashPilot worker
capability cutover. A worker must be online and report version `>= 1.18.21`;
older, unknown-version, or offline workers remain observation-only. This avoids
the unsafe behavior where a newer UI sends recreate/rotation requests to an
older worker that cannot execute the route.

## Explicit non-goals

This evidence does not justify changing protected providers, replacing node
identity, bypassing EarnApp blacklist/IP-quality policy, or bulk-upgrading
historical nodes. Those actions remain outside the canary scope.
