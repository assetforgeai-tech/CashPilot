# Provider Proxy Leak Audit

Status: source-contract audit; live packet capture remains required before production rollout.

| Provider | Runtime/network contract | Direct IPv4 | IPv6 | DNS/DoH | UDP/WebRTC | Reboot persistence |
|---|---|---|---|---|---|---|
| EarnApp | Docker runtime, Redsocks + iptables, fail-closed proxy | source contract only | unverified | source contract only | unverified | worker heartbeat/container persistence only |
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
| wipter | Existing provider adapter/runtime | unverified | unverified | unverified | unverified | unverified |

Unknown is intentionally not treated as pass. A live audit must run from each worker namespace and record the observed egress IP, DNS resolver, IPv6 route, UDP behavior, and restart result without storing credentials.
