# Provider lifecycle/network matrix — 2026-09-11

This is a source-evidence matrix. A source contract is not live packet proof.

| Provider | Runtime modes | Collector | Lifecycle scheduler | Proxy/DNS packet proof | Status |
|---|---|---|---|---|---|
| EarnApp | dedicated Docker, proxy | earnings | dedicated 5-minute scheduler | partial runtime contract; live packet/reboot pending | partial |
| Earn.fm | direct + proxy | earnings | no shared mutation scheduler wired | unverified | unverified |
| IPRoyal | proxy | earnings | no shared mutation scheduler wired | unverified | unverified |
| Mysterium | direct | earnings | wallet heartbeat only; no generic mutation | unverified | unverified |
| NKN | direct | dashboard-only | provider-specific runtime flow | unverified | unverified |
| PacketStream | proxy | earnings | decision helper only; no mutation wiring | unverified | unverified |
| Proxies-SX | proxy | earnings | decision helper only; no mutation wiring | unverified | unverified |
| Proxybase | direct + proxy | dashboard-only | no shared mutation scheduler wired | unverified | unverified |
| Proxybase-XYZ | direct + proxy | count-only | no shared mutation scheduler wired | unverified | unverified |
| ProxyRack | direct + proxy | earnings | no shared mutation scheduler wired | unverified | unverified |
| Repocket | direct + proxy | earnings | no shared mutation scheduler wired | unverified | unverified |
| Spide | direct + proxy | dashboard-only | no shared mutation scheduler wired | unverified | unverified |
| Traffmonetizer | direct + proxy | earnings | no shared mutation scheduler wired | unverified | unverified |
| UpRock | proxy | count-only | no shared mutation scheduler wired | unverified | unverified |
| URnetwork | direct + proxy | dashboard-only | no shared mutation scheduler wired | unverified | unverified |
| Wipter | proxy + managed sidecar | count-only | migration/reconciliation hooks | post-DNS packet/reboot proof pending | partial |

## Findings

1. `app/main.py` schedules the EarnApp lifecycle evaluator explicitly every five minutes. `app/provider_lifecycle.py` is a pure decision helper; it does not execute mutations.
2. Therefore the catalog's `lifecycle_actions` must not be read as proof that every provider is operationally auto-restarted/recreated/rotated.
3. Provider-wide zero-leak remains unproven until each active runtime has packet capture and reboot evidence.
4. This matrix intentionally leaves unsupported or untested providers `unverified`; no generic mutation was enabled during the audit.
