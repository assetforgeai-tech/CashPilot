# Proxy Lease Safety Impact Map

## Scope

This change tightens only the selection of a **new** Proxy Pool candidate. It
does not delete an endpoint, release an assignment, mutate a provider identity,
recreate a worker/provider container, or rewrite an existing lease.

## Shared legacy contracts

### `database.lease_proxy_for_worker()`

- `app/main.py::_proxy_for_worker_instance()` calls this when a worker has no
  usable legacy assignment. If no authoritative candidate exists, the caller
  receives `None` and keeps the existing hold/no-proxy behavior.
- `app/routers/proxies.py::api_worker_proxy_assignment()` calls this for an
  explicit operator request that asks CashPilot to choose a proxy. If no
  authoritative candidate exists, the request returns the existing no-proxy
  outcome rather than binding an unverified endpoint.

The function remains idempotent for a worker that already has an assignment:
the `ON CONFLICT(worker_id)` statement selects no replacement when there is no
eligible source row, so the existing assignment row is preserved.

### `database.find_available_proxy_for_worker()`

- `app/main.py::_proxy_for_worker_instance()` calls this before an acknowledged
  sidecar rotation. Returning `None` leaves the current binding intact.
- `app/routers/proxies.py::run_proxy_pool_recheck()` calls this after a generic
  probe proves an assigned proxy dead. Returning `None` skips rotation and does
  not clear the old assignment.
- `app/routers/proxies.py::api_worker_proxy_assignment()` uses this for workers
  with active proxy instances so runtime apply/ack remains the commit guard.

## Scoped provider contract

`database.lease_proxy_for_provider_instance()` already requires generic
`status='alive'`, a non-empty endpoint `exit_ip`, and a canonical unused egress.
For provider `earnapp`, the latest eligible `CID_SET` evidence must additionally
carry the same non-empty egress IP as the current endpoint. Historical probe
rows remain available for audit; they simply stop authorizing a lease after the
generic egress changes.

Existing scoped leases are returned before candidate selection and remain
unchanged. This is deliberate: the patch prevents unsafe **new** allocation and
does not silently rotate a running provider.

## Protected state

The following are outside the write path and must remain unchanged:

- protected provider source/runtime contracts;
- `cashpilot-worker` image, container ID, start time, identity, and heartbeat;
- provider containers, identities, volumes, wallets, and credentials;
- live `proxy_assignments` and `provider_proxy_leases` rows;
- Proxy Pool scheduler settings.

## Release boundary

All changed production files are part of the CashPilot UI image. The release may
publish both component jobs according to workflow path rules, but deployment is
limited to `cashpilot-ui`; `cashpilot-worker` must not be recreated.

## Verification

Local regression tests prove:

1. Unknown/dead/missing-egress endpoints cannot become new legacy assignments.
2. The reservation-free legacy candidate lookup follows the same rule.
3. An old EarnApp `CID_SET` cannot authorize a changed endpoint egress.
4. A fresh matching EarnApp probe restores eligibility.
5. Existing idempotent assignment and scoped-lease behavior remains green.

Live verification is read-only: query a copied database or run selection SQL in
a rolled-back transaction. Do not create, release, or rotate a live lease merely
to demonstrate the predicates.
