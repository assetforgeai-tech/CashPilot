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

## Exhaustive binary scope

The supplied verifier report confirms a complete comparison of the old and new
macOS binaries: both are `52,730,204` bytes, with `17,330` changed bytes in
`104` contiguous ranges. All differences are confined to seven pkg
`STORE_CONTENT` records (`client.js`, SDK/package metadata and duplicated
`zon_config`/package records); ELF headers, 14 program headers, 31 sections,
BuildID, native Node runtime, VFS, dictionary and pkg prelude are unchanged.

The seven-record diff is material for runtime compatibility but is not an
identity or account-link change. In particular, the new client:

- returns no LAN address when `skip_local_addr` is active, and resolves the
  interface from the supplied address with `_id.ifname`/`en0` and
  `_id.iface_type`/`eth` fallback;
- derives the `tunnel_init` response alias from `appid` and
  `tv_platform || node`, removes proxy/address and several installer/debug
  fields from the response, and forces the safe status flags;
- caps SDK tunnel-decline cooldown at two hours (the wrapper separately uses a
  bounded 60-3,600 second restart cooldown); and
- filters the complete Docker bridge range `172.16.0.0/12`, rather than only
  `172.17.*`.

Build metadata moves from `1.605.415` to `1.660.577` and from
`app_macr_mac` to `app_macr_mac_sdk`; installer/DMG makeflags are removed.
The verifier found no changes to UUID, serial, platform UUID, hostname, OS
fingerprint, proxy policy, OAuth/link flow or certificate pins. Those values
remain owned by the per-node profile and `boot.js` state.

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
