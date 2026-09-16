# Azure authority snapshot (2026-09-16)

Read-only server API snapshot after the `v1.53.15` worker rollout. Scoped to
Azure workers `118903` and `118904` only.

- Both workers reported `online`, `version=1.53.15`, heartbeat current, and
  `183/183` containers running.
- Provider rows were running for all returned families: EarnApp 20, EarnFM 40,
  IPRoyal 20, Mysterium 2, PacketStream 20, Proxies-SX 20, ProxyBase 40,
  ProxyRack 40, Repocket 40, Spide 40, Traffmonetizer 40, UpRock 2, URNetwork
  40, and Wipter 2.
- Collector status was connected for all returned families except Repocket and
  Traffmonetizer, which reported `collector_disconnected=true`.
- Known balances were returned for EarnApp, EarnFM, IPRoyal, Mysterium,
  PacketStream, Proxies-SX, ProxyRack, Repocket, Traffmonetizer, and UpRock;
  ProxyBase, Spide, URNetwork, and Wipter remain balance-unknown by design or
  due to collector coverage.

This is operational inventory evidence, not proof that every provider has
positive earnings or that every network lane has passed the security matrix.
Repocket/Traffmonetizer collector recovery remains an open production gate.
