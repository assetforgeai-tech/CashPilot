# NKN current ACK blocker

Captured 2026-09-15 after worker restart and socket refresh.

## Authoritative state

- Azure workers `118903` and `118904` report healthy worker heartbeats.
- The restricted helper is active on both hosts.
- `/run/cashpilot-nkn-agent/agent.sock` is visible inside both worker containers.
- Worker `118904` has six NKN assignments with current server leases, but all
  six local runtime records are `lease_guard_suspended=true` and stopped.
- Server heartbeats continue returning HTTP `200`.
- The latest server-side rows retain the leases; no stale lease was released.

## Interpretation

Transport visibility is fixed. The remaining failure is ACK/state reconciliation:
the worker has not received or applied a matching ACK for those assignments.
The exact CAS tuple remains mandatory before any resume or cleanup. No stale
container, wallet volume, or lease was deleted.

## Guard behavior

The worker now avoids issuing duplicate suspend requests once an assignment is
already suspended. Only a matching server ACK can clear the guard and resume
the runtime.
