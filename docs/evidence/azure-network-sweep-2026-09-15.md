# Azure network sweep - 2026-09-15

Scope: production workers `118903` (East Asia) and `118904` (Japan East). Read-only checks; no firewall or container mutation.

## Worker baseline

| Worker | Host | Worker | Managed containers | IPv6 default route |
|---|---|---|---:|---|
| 118903 | cashpilot-live-ea | healthy, restart 0, `1.51.12` | 285 | none observed |
| 118904 | cashpilot-live-je | healthy, restart 0, `1.51.12` | 271 | none observed |

Both hosts resolve through local `127.0.0.53`. Host-level IPv4/IPv6 UFW chains report policy `OUTPUT ACCEPT`; this is not proof of per-container fail-closed isolation. Provider-side evidence must therefore come from each runtime/sidecar probe.

## Findings

- East Asia has two `proxies-sx` containers in restart loops (`553` and `567` restarts). This is an operational failure and must not count as healthy/earning evidence.
- The affected containers use the persisted pre-hardening command (`wget ... reference-sdk.js` without the atomic retry path). Logs show repeated TLS resets, DNS failures, and HTTP 502 responses before intermittent relay connections. The catalog contains the hardened command, but an existing deployment's recorded spec is retained until an explicit redeploy.
- The current worker inventory has no IPv6 default route, but per-container IPv6 blocking/tunneling remains unverified.
- Per-provider egress, DNS, DoH/DoT, UDP, and direct-fallback evidence remains incomplete for several lanes; existing reconciliation intentionally reports `attention` for those lanes.

## Decision

No production-ready claim yet. Fix or quarantine the two Proxies.sx crash-loop instances, then rerun lane-specific probes. Do not change host firewall globally because direct-provider lanes require provider-native networking.
