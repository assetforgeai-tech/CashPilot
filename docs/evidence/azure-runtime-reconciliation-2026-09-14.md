# Azure Runtime Reconciliation - 2026-09-14

Scope: workers `118903` (East Asia) and `118904` (Japan East) only.

## Snapshot

- Both workers: `online`, heartbeat current, worker image `1.51.3`, Docker available.
- Cycle manifest: `azure-cycle-2026-09-14-cycle-1.json`.
- Runtime inventory: 354 provider containers (`183` + `171`) reported by CashPilot.
- Generic plans: `ready`; desired/running counts match for both workers.
- Dedicated/manual providers remain adapter-scoped; no generic deployment was forced.

## Finding

`proxies-sx` East Asia containers `proxy-001` and `proxy-002` were reported as running while Docker showed restart counts around 170 and logs showed repeated TLS/DNS failures fetching `https://agents.proxies.sx/peer/reference-sdk.js`. This is a real runtime failure, not an earning proof.

The catalog command was hardened in the worktree to download into a temporary file, retry five times with a 10-second delay, atomically rename on success, and fail closed when the SDK is absent. It is not yet active on the Azure workers because the worker image has not been rebuilt/released.

Spide dashboard absence was traced to a second contract drift. The proven raw setup logs in with account email/password and registers the emitted Device key using form encoding. CashPilot previously required a separately pasted dashboard token and sent JSON. The worktree now follows the raw login/register contract, retaining the pasted token only as a compatibility fallback.

The worker status path now exposes `restart_count` and reports a recent crash loop as `runtime_health=restart_loop` and `status=degraded`; aggregate running counts exclude that state. Regression coverage passes.

## Remaining gaps

- Several proxy lanes lack observed egress evidence in reconciliation.
- Several direct lanes lack DNS/IPv6/direct-fallback evidence.
- Provider dashboard traffic/earnings deltas are not yet authoritative for every provider.
- Full reboot and clean/redeploy cycle 2 remain pending.
