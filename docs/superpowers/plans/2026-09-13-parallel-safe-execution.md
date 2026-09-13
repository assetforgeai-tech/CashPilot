# Parallel Safe Execution Matrix

## Coordinator gate

Only the coordinator may merge, publish images, change live workers, mutate leases, rotate proxies, delete/recreate nodes, or promote production. Every worker returns a diff, focused tests, and redacted evidence.

## Parallel lanes

| Lane | Ownership | Allowed work | Completion gate |
| --- | --- | --- | --- |
| Source/policy | `app/provider_runtime.py`, `app/provider_lifecycle.py`, related tests | Policy contracts and unit tests | Focused tests + Ruff |
| UI | `app/templates/`, `app/static/`, UI tests | Settings navigation, capacity/error presentation | Static tests + browser audit |
| Security/network | `app/provider_network_audit.py`, probe tests/docs | Fail-closed evidence and leak checks | Security review + probe matrix |
| Live evidence | `docs/evidence/`, read-only scripts | Worker/provider inventory and canary probes | Redacted command output |

## Sequential gates

1. Review all diffs and check ownership boundaries.
2. Run focused tests, then full regression and lint.
3. Build immutable UI/worker images and verify digests.
4. Redeploy server, then workers one at a time; verify health, restart policy, mounts, and worker identity.
5. Run one provider/lane canary at a time; verify lease, egress, lifecycle, and rollback.
6. Promote only when every required evidence item is `pass`; unknown remains `pending`.

## Current checkpoint

- Source/UI/security changes are merged in this worktree and pass focused tests.
- Server and both Azure workers run `v1.46.2` with preserved identity/volumes.
- Live provider/network evidence is still pending; production promotion is not authorized yet.

## Safety invariants

- No `docker compose down -v` on identity-bearing services.
- No bulk provider redeploy.
- No cross-provider proxy mask or EarnApp policy action.
- No secret/token/private-key output in logs or evidence.
- Abort on image, volume, worker-ID, lease, or network-contract drift.
