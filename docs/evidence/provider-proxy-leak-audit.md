# Provider Proxy Leak Audit

Status: read-only live audit completed for the currently running EarnApp containers on `vps-test-us` (`eapp`, 2026-09-10). Other providers were not running on that worker and remain unverified.

| Provider | Runtime/network contract | Direct IPv4 | IPv6 | DNS/DoH | UDP/WebRTC | Reboot persistence |
|---|---|---|---|---|---|---|
| EarnApp | Docker runtime, Redsocks + iptables, fail-closed proxy | observed proxy egress; DB lease correlation pending | blocked by `CP_EARNAPP6_OUT` | local `127.0.0.1:53` + DNS redirect observed | non-DNS UDP has no allow rule; packet capture pending | `restart=always` observed; reboot evidence in dated canary report |
| NKN | Provider runtime-specific | unverified | unverified | unverified | unverified | unverified |
| earnfm | Existing provider adapter/runtime | unverified | unverified | unverified | unverified | unverified |
| iproyal | Existing provider adapter/runtime | unverified | unverified | unverified | unverified | unverified |
| mysterium | Host/direct wallet runtime | unverified | unverified | unverified | unverified | unverified |
| nkn | Direct node runtime | unverified | unverified | unverified | unverified | unverified |
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

- Worker `v1.28.1` is healthy and sends confirmed container inventory.
- The live reconciliation endpoint reports Wipter `attention` with the runtime
  untracked (`wipter`) rather than treating it as safe.
- Wipter restart-loop evidence remains: `restart count 28473`, repeated
  `/etc/machine-id: Permission denied`; `OOMKilled=false`. The current runtime
  was deployed before the catalog's `DAC_OVERRIDE` capability and managed
  proxy-sidecar contract were applied.
- No Wipter proxy lease, account, volume, or container was changed during this
  audit.
