# Provider Policy Matrix

| Provider class | Modes/topology | Allocation and ownership | Health/lifecycle | Evidence boundary |
|---|---|---|---|---|
| EarnApp | Proxy lane; slot-based; dedicated Docker platform policy | Account-scoped sticky ownership; exclusive account; serialized account/link queue | Node-level health; provider rejection rotates/recovers by declared policy; account auth failure is distinct | Worker/DB tuple first; provider dashboard and collector verify usage/auth |
| Pawns/IPRoyal | Provider-private proxy lane; slot-based | Private allocator lane; honor provider `ip_used`; do not share admission decisions with EarnApp | Provider-specific probe/rotation | Provider dashboard/collector only confirms external state |
| MYST | Direct-only dedicated runtime | Wallet-scoped, no proxy lease | Wallet/runtime health | Direct route and wallet collector |
| NKN | Direct-only dedicated runtime | Wallet-scoped, no proxy lease | Dashboard/collector policy; no proxy fallback | Worker plus provider observation |
| Earn.fm | Direct and proxy lanes; slot-both | Lane-isolated leases; proxy lane uses eligible capacity | Lane-specific health; no direct/proxy fallback | Egress/probe plus provider observation |
| Proxybase/Proxyrack | Direct and proxy lanes where catalog permits | Explicit lane leases; no inferred cross-lane ownership | Adapter-specific transport and provider probes | Worker network evidence plus dashboard/collector |
| Packetstream, Repocket, Traffmonetizer, proxies.sx, and other proxy providers | Explicit catalog modes; generally proxy/slot topology | Provider-scoped lease and adapter-owned credentials | Provider adapter decides probe/retry/rotation; no generic assumption | Runtime evidence plus provider-specific external evidence |

## Invariants

- EarnApp and Pawns/IPRoyal allocator lanes never share account or admission
  state.
- MYST/NKN never receive proxy leases.
- A proxy shortage makes a proxy plan pending; it does not reduce the requested
  topology or invent direct fallback.
- `direct_fallback` and `proxy_fallback` remain false unless a provider contract
  explicitly says otherwise.
- Migration-source additions are candidates, not retained behavior, until the
  matrix is updated with code, test, and evidence.
