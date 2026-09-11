# Provider Proxy Leak Audit

Status: read-only live audit completed for the currently running EarnApp containers on `vps-test-us` (`eapp`, 2026-09-10). Other providers were not running on that worker and remain unverified.

| Provider | Runtime/network contract | Direct IPv4 | IPv6 | DNS/DoH | UDP/WebRTC | Reboot persistence |
|---|---|---|---|---|---|---|
| EarnApp | Docker runtime, Redsocks + iptables, fail-closed proxy | observed proxy egress; DB lease correlation pending | blocked by `CP_EARNAPP6_OUT` | local `127.0.0.1:53` + DNS redirect observed | non-DNS UDP has no allow rule; packet capture pending | `restart=always` observed; reboot evidence in dated canary report |
| NKN | Provider runtime-specific | unverified | unverified | unverified | unverified | unverified |
| earnfm | Existing provider adapter/runtime | unverified | unverified | unverified | unverified | unverified |
| iproyal | Existing provider adapter/runtime | unverified | unverified | unverified | unverified | unverified |
| mysterium | Host/direct wallet runtime | unverified | unverified | unverified | unverified | unverified |
| packetstream | Existing provider adapter/runtime | unverified | unverified | unverified | unverified | unverified |
| proxies-sx | Existing provider adapter/runtime | unverified | unverified | unverified | unverified | unverified |
| proxybase | Existing provider adapter/runtime | unverified | unverified | unverified | unverified | unverified |
| proxybase-xyz | Existing provider adapter/runtime | unverified | unverified | unverified | unverified | unverified |
| proxyrack | Existing provider adapter/runtime | unverified | unverified | unverified | unverified | unverified |
| repocket | Existing provider adapter/runtime | unverified | unverified | unverified | unverified | unverified |
| spide | Existing provider adapter/runtime | unverified | unverified | unverified | unverified | unverified |
| traffmonetizer | Existing provider adapter/runtime | unverified | unverified | unverified | unverified | unverified |
| uprock | Existing provider adapter/runtime | unverified | unverified | unverified | unverified | unverified |
| urnetwork | Existing provider adapter/runtime | unverified | unverified | unverified | unverified | unverified |
| wipter | Proxy-only contract; managed sing-box sidecar required | **attention** | unverified | **host DNS observed** | unverified | unverified |

Live EarnApp observations:

- `cashpilot-earnapp-canary-us-fresh-ios-02`: IPv4 `116.98.229.8`; resolver `127.0.0.1`; Redsocks `127.0.0.1:12345`; local DoH listener `127.0.0.1:1053`; `CP_EARNAPP_OUT` terminal DROP; `CP_EARNAPP6_OUT` terminal DROP; Docker `restart=always`.
- `cashpilot-earnapp-canary-us-ios-04`: IPv4 `171.251.99.76`; same fail-closed/DNS contract; EarnApp process opened UDP sockets, but no non-DNS UDP allow rule exists, so this is not proof of usable or leaked UDP traffic.
- `cashpilot-earnapp-prod-us-20260908-macos-10`: IPv4 `14.243.208.175`; same fail-closed/DNS contract; IPv6 HTTP probe failed; Docker `restart=always`.

Unknown is intentionally not treated as pass. A complete fleet audit still requires each active provider runtime on each worker, DB lease-to-egress correlation, packet capture for UDP/WebRTC, and a controlled reboot check. No mutation was performed during this audit.

## Wipter finding (2026-09-10)

The active `cashpilot-wipter` container on the CashPilot server is running in
Docker `bridge` mode without a managed egress sidecar. Its observed IPv4
egress is the VPS address `42.96.13.215`, and its resolver uses host DNS
`103.121.88.11`/`103.121.88.12`. This is a direct-egress risk and does not
satisfy the proxy-only contract in `services/depin/wipter.yml`.

CashPilot now exposes this drift through the read-only
`/api/admin/provider-network/reconciliation` endpoint and Settings UI. It does
not mutate, stop, or redeploy Wipter. Migration requires a provider-specific
canary with volume/account preservation, proxy egress verification, and
rollback evidence.

## Post-worker rollout evidence (2026-09-10)

- Worker `v1.31.0` is healthy and sends confirmed container inventory.
- The live reconciliation endpoint reports Wipter `attention` with the runtime
  untracked (`wipter`) rather than treating it as safe.
- Wipter restart-loop evidence remains: `restart count 29277+`, repeated
  `/etc/machine-id: Permission denied`; `OOMKilled=false`. The current runtime
  was deployed before the catalog's `DAC_OVERRIDE` capability and managed
  proxy-sidecar contract were applied.
- No Wipter proxy lease, account, volume, or container was changed during this
  audit.

## v1.32.0 rollout and ownership backfill (2026-09-10)

- UI and worker run `v1.32.0`, both healthy.
- EarnApp API reports `sticky_owned=8`, `eligible=309`, `leaseable=301`, and
  `occupied=8` after the idempotent legacy-lease backfill.
- Proxy Pool reports the `zlproxy` group with `817` eligible, `804` available,
  `13` leased, `12` sticky-owned, and `139` duplicate-egress endpoints.
- Wipter container ID and `wipter-data` volume remain unchanged; its direct
  egress and restart loop remain an open finding.

## Wipter guarded migration (2026-09-10)

- The owner-gated migration leased one residential proxy and completed through
  the worker rollback transaction.
- Main runtime uses `network_mode=container:<sidecar-id>`; managed sing-box
  sidecar is running.
- Main runtime has `NET_ADMIN`, `NET_RAW`, and `DAC_OVERRIDE`; restart count is
  `0` after migration.
- The original `wipter-data:/root/.config/wipter-app` volume is mounted.
- Worker evidence reports `authenticated=true`, `earning=true`, and
  `traffic_seen=true`; Wipter logs show HTTPS upload/download and PONG traffic.
- A reconciliation alias fix maps the durable DB instance `wipter-proxy` to the
  legacy heartbeat slug `wipter`; no runtime rename is required.

## Wipter live recheck (2026-09-11)

- Read-only inspection confirms `cashpilot-wipter` runs in the exact network
  namespace of `cashpilot-wipter-egress` (`network_mode=container:<sidecar-id>`),
  with `NET_ADMIN`, `NET_RAW`, and `DAC_OVERRIDE`.
- Both containers are running with `restart=always`, restart count `0`; the
  original `wipter-data` volume remains mounted read-write.
- Recent Wipter logs contain repeated `PONG` traffic. This supersedes the
  earlier pre-migration direct-egress/restart-loop finding; no direct-egress
  claim is made without a fresh packet capture.
