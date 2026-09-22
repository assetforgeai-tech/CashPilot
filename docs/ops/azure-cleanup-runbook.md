# CP-014J Azure Cleanup Runbook

## Safety gate

Run the inventory command first. The default is read-only and must produce a
secret-free before-inventory. No cleanup is allowed without fresh approval that
names the exact `cashpilot-cp014j-*` resources. `cashpilot-live-ea` and
`cashpilot-live-je` are always out of scope.

## Sequence

1. Capture read-only Azure inventory.
2. Export worker, proxy, wallet, runtime, and capacity ownership.
3. Run the cleanup script in dry-run mode and review the exact target list.
4. Obtain fresh operator approval.
5. Delete only approved CP-014J VM names and dependent resources.
6. Verify zero orphan resources and preserve account credentials, sticky egress,
   PayPal ownership, and earnings history.
7. Create one East Asia worker only after the cleanup evidence is accepted.

Evidence must record before/after inventory, exact scope, command results, and
zero orphan verification. Stop on any mismatch; never use a broad resource-group
delete.
