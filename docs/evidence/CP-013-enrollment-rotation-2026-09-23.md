# CP-013 enrollment-key rotation evidence

- Scope: CashPilot control-plane, `cashpilot-live-ea`, and `cashpilot-live-je` only.
- PR #493 merged before mutation (`4b9e41e44ceac303dd3060c90ccddeffb0e2945a`).
- Shared enrollment key replaced with a fresh URL-safe key. Secret value is not recorded here.
- Control-plane `/fleet/.fleet_key`: mode `600`, owner `1000:0`; UI loaded the key successfully.
- EA and JE worker compose configs updated; only `cashpilot-worker` was recreated.
- Heartbeat verification: EA `200 OK`; JE `200 OK`.
- Final worker images: EA `cashpilot-worker:cp013-v1.65`; JE `cashpilot-worker:cp013-v1.65-je`.
- Final state: worker containers healthy; running-container counts unchanged (EA `286`, JE `285`).
- `/data/.worker_key` and `/data/.worker_id` remained present with unchanged hashes per worker.
- Provider containers/nodes, proxy leases, NKN/Myst wallets, account pools, runtime volumes, VMs, and Azure resources were not deleted or recreated.
- An intermediate text/ownership issue caused temporary `503` heartbeats; corrected by restoring the original image pins, setting fleet-key ownership to `1000:0`, and restarting only UI/worker. Final heartbeat gates passed.
