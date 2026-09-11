# CashPilot capability map — pre-live baseline

This map describes shipped surfaces, policies, and dependencies. It is an audit
inventory, not permission to mutate live providers.

## Product surfaces

- Dashboard: aggregate earnings, node counts, health, net earnings, collector alerts, exchange-rate display, update banner.
- Setup Wizard: service selection, worker selection, credential input, proxy eligibility, resource/preflight checks, sequential deployment.
- Service Catalog: provider metadata, platforms, runtime mode, credentials, payout model, limitations, deploy risk, disclosure.
- Fleet: worker health, heartbeat age, key confirmation, container inventory, CPU/memory/storage/power settings, worker commands.
- Proxy providers: imported source providers, provider credentials, import/check/recheck/delete controls, raw/duplicate handling.
- Proxy Pool: protocol, location, IP type, egress IP, live status, latency, EarnApp qualification, UDP capability, duplicate-egress groups, assignment, pagination, filters, delete-all confirmation.
- Settings: environment references, auto deploy, provider credentials, collector metadata, EarnApp account pool, token alerts, capacity, recovery, platform policy, runtime limits, PayPal pool, NKN settings, ChainDB publisher.
- Payouts: destination registry, service payout state, balances, payout history, confirm/reject actions, risk and progress.
- Wallets: MYST and NKN wallet pools, lease/release state, provider balances, node/wallet mapping.

## Provider/runtime families

- EarnApp: dedicated Docker platform lanes; MacOS/iOS emulation and official Ubuntu Docker lanes; residential proxy required; one node per egress/account constraints; Redsocks/iptables/sidecar fail-closed network policy; account collector and node lifecycle evidence.
- NKN: direct public-IP slot deployment; one node per direct IP; Docker/LXD runtime helpers; beneficiary address; wallet pool; official JSON-RPC collector; ChainDB publisher/cache workflow.
- Earn.fm, IPRoyal/Pawns, PacketStream, Proxies-SX, Proxybase, Proxybase-XYZ, ProxyRack, Repocket, Spide, Traffmonetizer, URnetwork: catalog-driven Docker/proxy runtimes with provider-specific credentials, limits, collectors, and payout metadata.
- Mysterium: wallet/direct runtime family with persistent identity and wallet semantics.
- UpRock: official Linux package/state-bundle runtime with provider-specific installer assets.
- Wipter: Docker runtime migrated behind managed sing-box sidecar; persistent account volume; migration/rollback guard; live DNS post-fix proof still pending.

## Core policies

- Worker bootstrap: worker identity, key enrollment, heartbeat, capabilities, network slots, runtime inventory, restart persistence.
- Auto deploy: stable-worker gate, provider ordering, one-provider/one-node sequencing, platform and proxy eligibility.
- Proxy lifecycle: import, metadata check, live probe, protocol/location/IP-type classification, egress duplicate detection, lease CAS, release, sticky ownership, quarantine, rotation.
- EarnApp ownership: active lease release is reversible; egress ownership persists while account exists; account deletion explicitly releases ownership.
- EarnApp lifecycle: observe/restart/recreate/rotate decisions, earnings-cycle/flatline evidence, offline/banned handling, recovery hold, replacement ticket, worker-authoritative presence.
- Heartbeat: worker health and inventory reconciliation; stale worker detection; capability gating before mutation.
- Reconciliation: DB rows versus heartbeat inventory versus Docker/container presence; reports drift and alerts before any deletion.
- Payments: collector payment methods, auto-redeem configuration, PayPal assignment/quarantine foundation, payout registry and manual payout actions.
- Token handling: encrypted credential storage, expiry evidence, token-health alerts, collector retry; live Chrome-profile auto-import remains unverified.
- Security: auth/session rotation, owner/writer/read-only roles, rate limits, CSP/security headers, host-key pinning, secret redaction, bounded subprocess/SSH, fail-closed routes.

## Scheduled/background behavior

- Worker heartbeat ingestion and stale-worker monitor.
- EarnApp hourly collection and lifecycle evaluation.
- Recovery-hold expiration and replacement-ticket state.
- Collector alerts and update checks.
- Provider-specific automation hooks and reconciliation.
- NKN ChainDB publisher timer and failure service.

## External dependencies

- Docker Engine and worker API.
- GitHub/GHCR release and image publication.
- Provider APIs/dashboards: EarnApp, NKN, Earn.fm, IPRoyal, PacketStream, etc.
- Residential proxy providers and metadata/probe services.
- Cloudflare R2 for NKN ChainDB snapshots.
- SSH/ssh-agent/sshpass for owner-authorized NKN publisher deployment.
- Chrome profile 40 for the requested browser/UI/token verification.

## Current evidence status

- Automated backend/security regression suite: passing.
- EarnApp sticky ownership/capacity: verified from prior production evidence.
- Wipter migration code: regression-tested; post-fix packet/reboot evidence pending.
- Provider-wide zero-leak: incomplete; non-tested providers remain `unverified`.
- Full UI/UX browser interaction sweep: blocked by unavailable Chrome connector.
- PayPal live pool behavior, token auto-import, common provider account adapters, and lifecycle wiring for every provider: incomplete.
