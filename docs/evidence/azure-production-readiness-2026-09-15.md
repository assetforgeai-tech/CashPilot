# Azure production readiness status

Scope: Azure workers `118903` and `118904` only.

## Proven

- Both workers run `cashpilot-worker:1.52.6`, healthy after sequential reboot.
- Worker identity/data volumes and provider container IDs survived guarded rollout.
- Startup systemd units now pin `1.52.6`, use Compose project `cashpilot`, and stop only the worker.
- Spide fresh registration matches the raw form/XHR contract; 40/40 local devices were online in the provider API.
- NKN helper recovery is exact-CAS and secret-free. Unmatched stale LXD containers are not adopted or deleted.
- Current topology contains all 15 configured provider families across the two workers.

## Not yet production-ready

- Provider network reconciliation: 34 reports, 11 pass, 23 attention.
- Main gap: many proxy lanes lack authoritative observed-egress evidence even when fail-closed controls are present.
- Dedicated runtime tracking gaps remain for UpRock/Wipter on worker `118904`.
- NKN server leases were reclaimed while stale LXD remnants remained. A fresh authoritative assignment/runtime proof is still required.
- Provider dashboards still need current usage/traffic deltas beyond the completed Spide proof.
- Clean/deploy cycle 2 has not run.

No production-ready claim is made from this snapshot.
