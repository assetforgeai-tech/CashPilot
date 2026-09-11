# Provider Input Readiness — 2026-09-11

Status: `inventory-complete`, live deployment gate `pending`.

## Server inventory

- Workers: 5 online, 1 offline. The two clean Azure workers are online and heartbeat-authenticated.
- Provider instances: 50 total; 5 EarnApp running and 16 EarnApp verification-pending.
- EarnApp accounts: 2 active, 2 deleted. Active records have credentials stored encrypted; expiry fields are available for cookie policy.
- Proxy endpoints: 1,254 total; 985 alive, 269 dead. Geo: 953 verified, 32 inferred, 269 unknown. IP type: 985 inferred, 269 unknown. UDP probe: 0 positive.
- EarnApp logical nodes: 20 active, 50 planned, 6 recoverable, 9 retired.
- EarnApp egress ownership records: 20.
- Auto-deploy: configured `false` (`cashpilot_auto_deploy_enabled`); enabling it now would target every eligible online worker, including the existing fleet, not only the two clean Azure canary workers.

## Required follow-up

- Keep auto-deploy disabled until a worker-target scope exists or the operator explicitly accepts deployment to all eligible online workers.
- Resolve 269 dead/unknown proxy metadata records and the zero-positive UDP probe result before claiming provider-wide proxy readiness.
- Complete authenticated Chrome profile 40 provider audit; current CDP connector is unavailable, so provider UI/payment/token evidence remains `unverified`.
- Do not print raw provider credentials, cookies, API keys, passwords, proxy credentials, or GHCR tokens in evidence.
