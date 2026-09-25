# Proxy Route Contract

Status: CP-015A contract baseline. This document defines the shared safety
boundary; provider-specific adapters remain authoritative for provider policy.

## Provider lanes

| Lane | Providers | Route rule |
|---|---|---|
| Direct-only | Mysterium, NKN | Public IPv4/direct route. No proxy lease or fake-proxy wrapper. |
| Hybrid | EarnFM, ProxyBase, ProxyBase.xyz, ProxyRack, Repocket, Spide, TraffMonetizer, URNetwork | Direct and proxy lanes are separate deployments. A proxy shortage blocks only the proxy lane; it never silently falls back to direct. |
| Proxy-only | EarnApp, IPRoyal Pawns, PacketStream, Proxies.sx, UpRock, Wipter | Every provider instance requires an eligible proxy lease and a fail-closed route. Direct fallback is forbidden. |

EarnApp account/link/recovery rules and the Pawns/IPRoyal private allocator,
including `ip_used`, mask-and-replace, and admission decisions, remain separate.
Mysterium/NKN never receive proxy leases.

## Authority boundaries

| Component | May decide | Must not decide |
|---|---|---|
| Proxy Pool Probe | Upstream `alive`, `suspect`, or `dead`; durable probe evidence; rotation request | Provider identity, node deletion, lease release from one failure, direct worker callback |
| Route watchdog | Local route readiness; fail-closed `route_blocked`; stop the provider process so Docker can restart the same container | Upstream death, lease release, proxy rotation, provider recreate |
| Worker heartbeat | VPS/worker liveness and worker-resource reclaim policy | Proxy health or route health |
| Apply ACK + observed egress | Candidate binding and CAS replacement commit gate | Upstream liveness authority |

## Fail-closed invariants

- Proxy lanes have no direct fallback.
- Provider TCP traffic uses the declared route backend (`redsocks`/iptables or
  the approved sidecar backend); no undeclared bridge path is accepted.
- DNS/DoH/DoT, IPv6, UDP, and direct traffic are blocked or routed according to
  the provider-port matrix. Missing evidence is `unverified`, never safe.
- Route readiness requires startup grace, helper readiness, firewall-chain
  readiness, and the expected egress check.
- Route-health TTL is independent of lease ownership. The canary defaults are
  a 30-second route probe, a 90-second TTL, and three consecutive failed route
  probes before `route_blocked`.
- TTL expiry or watchdog failure may request a recheck and stop the provider;
  it must not release a lease or mark an upstream proxy dead. The watchdog
  must not mark an upstream proxy dead.
- Rotation commits only after candidate apply, worker ACK, observed egress,
  and one CAS transaction succeed. The old lease remains reserved until then.
- Sidecar/runtime images use immutable digests. `latest` is forbidden.

## Evidence boundary

Packet-level evidence must cover TCP, DNS/DoH, IPv6, UDP, direct-fallback,
egress, watchdog, and reboot behavior for each applicable provider group.
Evidence contains no token, cookie, password, wallet, database, or provider
raw response.
