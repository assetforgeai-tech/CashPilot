# EarnApp Multi-Platform Production Audit (2026-08-31)

## Decision

EarnApp is a proxy-only provider with geo-selected runtime lanes:

| Proxy qualification | Runtime | Backend |
|---|---|---|
| VN residential and EarnApp-allowed | MacOS or iOS emulation | dedicated Docker contract |
| Known non-VN residential and EarnApp-allowed | Official Linux x64 | dedicated Ubuntu LXD contract |

Generic catalog/raw Docker deployment remains closed. Existing protected
EarnApp nodes and every other protected provider remain immutable.

## Source evidence

The `earnapp_new_update` forensic runtime bundles contain the Mac/iOS boot,
entrypoint, supervisor, profile and link/retry contracts. They require unique
persisted profile/volume identity, platform-specific app IDs and proxy-routed
control-plane traffic. Existing CashPilot identity and artifact validators are
reused; fresh profiles may be expanded, but protected profile bytes are never
rewritten.

## Canary requirements

Create multiple sequential nodes with distinct proxy IDs and egress IPs:

- two VN MacOS nodes;
- two VN iOS nodes;
- two non-VN Ubuntu LXD nodes.

Each node must prove unique UUID, correct account link, authoritative online
state, positive usage delta, restart persistence, and isolated proxy rotation.
One failure must be recorded and the next node attempted without blocking the
queue. No canary operation may target a protected logical ID or alias.

## Open live questions

Online-with-zero-usage, proxy transport qualification, and proprietary TLS or
control-plane behavior remain empirical canary questions. They must be measured
per platform/proxy/account and not inferred from local process health alone.
