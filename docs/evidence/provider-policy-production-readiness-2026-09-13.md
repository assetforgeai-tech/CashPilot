# Provider Policy Production Readiness - 2026-09-13

## Source verification

- Pawns/IPRoyal is declared `policy_group=pawns`, `proxy_allocation_policy=provider_private`, and `proxy_failure_scope=provider`.
- An IPRoyal `ip_used` rejection is masked and replaced inside the IPRoyal scope; no EarnApp or other provider mask is created.
- EarnApp is declared `policy_group=earnapp`, account-scoped authentication, sticky egress ownership, and node-scoped proxy failure handling.
- EarnApp `offline`, `usage_stalled`, and node `banned` decisions resolve to `restart`; account authentication/suspension resolves to observation/manual handling.
- Direct-only, proxy-only, and hybrid lanes remain independent and fail closed without cross-lane fallback.

## Dashboard verification

- Settings navigation exposes `Accounts`, `EarnApp input`, `Runtime`, `Collector`, and `Payment` anchors.
- Provider account rows show account state plus proxy `available / eligible` capacity when the database has evidence; unknown capacity stays `—`.
- No credential, token, or raw payment destination is rendered by the account-pool response or UI.

## Automated evidence

- `pytest tests/test_provider_account_pools.py tests/test_provider_lifecycle_policy.py tests/test_earnapp_settings_ui.py -q` -> `39 passed`.
- `pytest tests/test_provider_topology.py tests/test_provider_topology_api.py tests/test_settings_contract.py -q` -> `67 passed`.
- `python -m compileall -q app` -> passed.
- `git diff --check` -> passed.

## Deployment evidence

- Server `42.96.13.215`: UI and worker run `v1.46.2`, both healthy, restart policy `unless-stopped`, worker identity volume present.
- Azure workers `20.187.79.110` and `20.210.93.220`: worker runs `v1.46.2`, healthy, restart policy `always`, `/data/.worker_id` present.
- Existing provider runtimes were not redeployed during this rollout.
- Runtime hardening: generated proxy wrappers now require `ip6tables`, set `umask 077`, and chmod redsocks credential files `0600`; missing IPv6 firewall tooling aborts startup.
- TLS probe audit: EarnApp WSS qualification uses certificate and hostname verification; forged `CID_SET` evidence is rejected.
- Settings UI audit: major settings sections have shortcuts; mobile inline form rows stack below 768px; capacity is exposed as an accessible live region.

## Remaining live gates

Source tests do not prove live deployment. Production status remains pending until the current `v1.46.2` UI/worker rollout, Pawns isolation canary, EarnApp node-health canary, worker reconciliation, and DNS/IPv6/UDP/DoH/DoT evidence are captured.

## 2026-09-13 proxy sidecar config drift

- Japan East PacketStream canary exposed stale writable sidecar config: the
  existing `.cashpilot-initialized` marker prevented current generated config
  from being written. Sing-box restarted with a config missing
  `route.default_domain_resolver` and exited before the provider joined its namespace.
- Sidecar bootstrap now writes a temporary config, validates it with
  `sing-box check`, atomically replaces `config.json`, then records the marker.
  This removes stale-config reuse while preserving the config volume.
- Regression coverage: provider/lifecycle/recovery subset passes (`107 passed`).
- The failed canary remains released. No provider promotion is claimed until a
  fresh eligible proxy canary proves egress, DNS, IPv6, UDP, and restart behavior.
