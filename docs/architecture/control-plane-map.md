# CashPilot Control-Plane Map

This map describes the canonical `origin/main` integration surface. The migration
worktree is evidence only until a slice is reviewed and accepted.

## 1. Dashboard/API -> validation -> database

HTTP routes in `app/main.py` and `app/routers/*.py` parse request models,
authenticate the caller through `app/auth.py`, validate provider/platform/mode
contracts, then call `app/database.py`. Provider deployment requests enter the
`DeployRequest`/`ProviderPlanRequest` paths; EarnApp account operations enter
`app/routers/earnapp_accounts.py`. Database writes are the logical source of
truth and must be conditional where identity, generation, or proxy ownership is
involved.

## 2. Planner -> allocator -> proxy lease/ownership

`app/provider_topology.py` builds lane-specific `ProviderNodePlan` values from
public-IP slots and discovered proxy capacity. `app/provider_runtime.py` supplies
the provider truth matrix. The deployment path in `app/main.py` selects a plan,
then `app/database.py:lease_proxy_for_provider_instance` performs the provider
scoped lease. Release uses
`app/database.py:release_proxy_for_provider_instance`; EarnApp additionally uses
`reserve_earnapp_proxy_candidate`, account control routes, and the exact node
generation/device/proxy tuple. A planner must not infer proxy capacity from IP
count.

## 3. Server -> authenticated Worker API -> Docker runtime

The server calls worker endpoints through `app/main.py:_proxy_to_worker` with the
worker authentication contract implemented in `app/worker_api.py:_verify_api_key`.
The worker validates the deployment spec, materializes declared runtime assets,
and controls Docker through `app/worker_api.py`, `app/orchestrator.py`,
`app/provider_runtime.py`, and `app/earnapp_runtime.py`. Runtime identity and
proxy configuration are separate persisted inputs; a worker must reject an
unauthorized or stale mutation rather than silently adopting it.

## 4. Worker heartbeat -> inventory -> reconciliation

Workers post `app/main.py:api_worker_heartbeat` with inventory and health facts.
The server records worker state and runtime inventory, then invokes provider
reconciliation through `app/database.py:sync_provider_runtime_inventory`,
`reconcile_provider_instances`, and the EarnApp-specific
`reconcile_earnapp_provider_instances`. Reconciliation is convergence logic,
not permission to delete unknown production state; authority and generation
checks precede any retirement.

## 5. Collector -> earnings/device state -> dashboard

Collector factories in `app/collectors/__init__.py` create provider adapters.
EarnApp account collection is coordinated by
`app/earnapp_collection.py:collect_account` and
`collect_active_accounts`, persisted as account snapshots, payment state, and
auth results in `app/database.py`, then exposed through API/UI routes. A
collector snapshot is observational and cannot override a newer worker or DB
authority record.

## 6. EarnApp account queue -> link -> verification -> recovery

EarnApp account credentials and operation serialization live in
`app/earnapp_canary.py` and `app/earnapp_lifecycle.py`; account routes are in
`app/routers/earnapp_accounts.py`. Node provisioning and binding use
`app/earnapp_recovery.py:provision_node`, `bind_earnapp_node_runtime`, and the
account-scoped proxy lane. Link/deploy actions pass through the dedicated
EarnApp deploy/runtime modules, then workload health is checked before the node
is considered usable. Recovery claims use generation CAS and one-time replacement
tickets; health/reconciliation paths are in `app/main.py` and
`app/worker_api.py`. Token/auth failure is an account signal, not proof that a
node or proxy is banned.

## Boundary rule

Every mutation must identify its owner scope (provider, account, node, worker,
generation, and proxy where applicable). Dashboard observations and collector
snapshots remain lower-authority evidence until reconciled.
