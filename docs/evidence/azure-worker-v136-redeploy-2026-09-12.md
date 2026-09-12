worker=20.187.79.110
ghcr.io/assetforgeai-tech/cashpilot-worker:1.36|sha256:028dd50bce920ac7bf927488096c22910307745876fecb90565a08c0f3b53617|always {"status":"ok","worker":"20.187.79.110"}
worker=20.210.93.220
ghcr.io/assetforgeai-tech/cashpilot-worker:1.36|sha256:028dd50bce920ac7bf927488096c22910307745876fecb90565a08c0f3b53617|always {"status":"ok","worker":"20.210.93.220"}

## Identity-preserving worker restore

- Initial release redeploy accidentally used a new Compose project volume, creating duplicate worker registrations `118903` and `118904`.
- Root cause: generated override used `cashpilot_cashpilot_worker_data` instead of existing `cashpilot-worker_cashpilot_worker_data`.
- Corrected both VPS containers to image `ghcr.io/assetforgeai-tech/cashpilot-worker:1.36`, digest `sha256:028dd50bce920ac7bf927488096c22910307745876fecb90565a08c0f3b53617`, restart policy `always`, existing worker-data volume.
- Original registrations `112494` and `112444` now report online with their original client IDs and version `1.36.0`.
- Duplicate registrations were not deleted; they remain preserved for explicit operator cleanup after reconciliation.

## Post-restore provider preflight

Authenticated read-only plan calls after identity restoration:

- Worker `112444`: 10/10 ready IPv4 slots; Earn.fm hybrid desired/deployable `20/20`; EarnApp proxy-only desired/deployable `10/10`; proxy capacity `821`/`820` respectively.
- Worker `112494`: same topology and capacity (`20/20` Earn.fm, `10/10` EarnApp; proxy capacity `821`/`820`).
- NKN remains `dedicated` and intentionally uses its dedicated planner.
- No provider deployment or proxy lease mutation was performed.
