# Policy and data-flow audit — 2026-09-11

## Scope

Read-only review of lifecycle decisions, EarnApp state transitions, proxy ownership, account/payment handling, collectors, and reconciliation. No live node was mutated.

## Verified in source

- EarnApp node lifecycle stores generation, proxy, worker, device, earnings-cycle, recovery, and heartbeat fields in the database.
- EarnApp verification uses an account-scoped lock and requires matching logical node/device evidence; stale dashboard rows cannot satisfy another node.
- Link retries enforce a 5-second minimum interval, five-attempt burst, and 300-second cooldown.
- Runtime specs enforce expected proxy egress, bridge networking, disabled UDP, resource limits, and platform-specific identity contracts.
- Proxy leases use active-instance and active-proxy uniqueness constraints; release is persisted with reason and timestamp.
- EarnApp account control routes are leased/released separately from provider-node proxy leases.
- PayPal configuration and assignment helpers exist, but live assignment, auto-redeem, delete, and quarantine behavior remain unverified.
- Generic `app/provider_lifecycle.py` is read-only decision logic. It returns `observe` for providers without a registered runtime and is not proof that every provider scheduler is wired.

## Not proven

- Common lifecycle mutation policy is not wired into every provider adapter/scheduler.
- Dashboard counters have not yet been reconciled against a live worker/container snapshot in this audit.
- Token expiry extraction and manual-login-gated Chrome import have no live evidence.
- Provider-wide proxy/DNS/IPv6/UDP leak behavior lacks packet and reboot evidence.
- Sticky egress ownership and EarnApp capacity have prior evidence, but this run did not mutate or revalidate live rows.

## Required decisions before live test

1. Expose Chrome profile 40 through a safe CDP/connector session for UI and token evidence.
2. Approve a read-only worker diagnostic window for packet capture and reboot-persistence checks.
3. Decide whether non-EarnApp providers receive lifecycle mutation wiring now or remain explicitly `unverified`/adapter-disabled.
4. Verify PayPal and token flows in a controlled account before enabling automation.

## Status

`PARTIAL`: source and automated behavior verified; live UI, fleet network, and external-account behavior remain unverified.
