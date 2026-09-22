# CP-011 disposable Azure canary runbook

Scope lock: subscription `0e4b9f20-f92f-4883-a598-3251b0016d65`, resource
group `rg-cashpilot-live-test-20260911`, VMs `cashpilot-live-ea` and
`cashpilot-live-je` only. Never pass `test-sing`, `test-us`, `sing`, `eapp`, or
any other worker ID to these commands. CP-011 must not perform production
rollout.

## Sequence

1. Read-only Azure snapshot: VM power/provisioning, NIC/IP/PIP, disk, NSG,
   worker image/health, slot map, routes, firewall, resolver, container list.
2. Validate the canary dry-run and select one disposable slug. Preserve a
   before hash of worker inventory, proxy leases, container names, and slot map.
3. Deploy through the authenticated normal CashPilot canary route. Do not use
   generic bulk auto-deploy. Record HTTP status and redacted response fields.
4. Verify runtime health, expected egress, DNS/DoH handling, IPv6 fail-closed,
   UDP policy, and direct-fallback blocking with packet evidence.
5. Inject watchdog failure only through the guarded disposable endpoint. Verify
   repeated unhealthy samples, rotation request, generation change, and old
   runtime preservation until replacement verification.
6. Reboot only the authorized worker if the test requires it. Verify worker,
   slot map, runtime identity, lease state, and dashboard/provider reconciliation.
7. Remove only the disposable slug/resources. Reconcile container count,
   leases, provider state, and worker health to the baseline hash/count.
8. On any failed gate: stop, preserve logs/pcap, run the documented rollback,
   and mark the gate `FAIL` or `INCONCLUSIVE`; never continue to another lane.

## Required evidence record

Use `docs/ops/cp011-canary-evidence.schema.json`. Every mutation needs a UTC
timestamp, exact authorized VM scope, redacted action/result, and rollback
reference. Secret values, cookies, provider tokens, SSH keys, and bearer values
must never enter evidence, command output, or Git.

## Acceptance

CP-011 is `PASS` only when all required gates are `PASS`, cleanup converges to
the baseline, and no out-of-scope resource appears in the mutation log. A
provider/dashboard usage signal is not inferred from container `running`; it
must be attributable to the disposable node and recorded separately.
