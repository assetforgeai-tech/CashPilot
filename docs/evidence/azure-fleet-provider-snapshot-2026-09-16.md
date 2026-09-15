# Azure fleet provider snapshot (2026-09-16)

Read-only CashPilot API snapshot for workers `118903` and `118904`.

## Workers

Both workers reported `online`, version `1.53.12`, and `183/183` containers
running. Heartbeats were current at capture time.

## Provider inventory

The API reported all 14 deployed catalog providers on both workers. Running
instance counts were: EarnApp `20`, Earn.fm `40`, IPRoyal `20`, Mysterium `2`,
PacketStream `20`, Proxies-SX `20`, Proxybase `40`, ProxyRack `40`, Repocket
`40`, Spide `40`, Traffmonetizer `40`, UpRock `2`, URnetwork `40`, and Wipter
`2`.

EarnApp, Earn.fm, IPRoyal, Mysterium, and Proxyrack returned known balances.
Spide and several manual/dashboard-only providers correctly returned no
synthetic balance. Repocket and Traffmonetizer reported collector-disconnected
status and remain open collector gates; no runtime mutation was performed.

The server log root causes were verified: Repocket lacked the required
`REPOCKET_FIREBASE_KEY`; Traffmonetizer received upstream `429 Too Many
Requests`. The Repocket source now requires the key from server environment,
and no key is hard-coded.

This snapshot proves worker/runtime inventory continuity, not provider-specific
dashboard earnings for every node.
