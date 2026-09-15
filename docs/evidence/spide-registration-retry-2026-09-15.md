# Spide registration retry verification

Captured 2026-09-15 after release `v1.52.4`.

## Change

Post-deploy registration now retries the same CLI `Device key` through five
registration windows. The existing idempotent `Device is already registered`
response remains success.

## Rollout

- Server UI: running the `v1.52.4` image, healthy.
- Server worker: running `ghcr.io/assetforgeai-tech/cashpilot-worker:1.52.4`, healthy.
- Azure workers `118903` and `118904`: running `ghcr.io/assetforgeai-tech/cashpilot-worker:1.52.4`, healthy.
- Worker data, slot volumes, worker identity, and provider container IDs preserved.

## Provider authority

- Spide API: `45` devices returned, `41` online at the verification snapshot.
- CashPilot Azure inventory: `40` Spide instances.
- All `40` runtime key hashes matched a dashboard device; no runtime key was missing from the dashboard.
- Daily statistics: `40/40` matched devices online with positive requests and traffic (`1,689` requests; `28,176,669` traffic bytes at the snapshot).

The CLI's periodic `Status: Device not registered!` line is not equivalent to
dashboard registration: the same runtime key is registered and producing
traffic. It is retained as a diagnostic signal, not used as sole registration
authority.

## Remaining gate

Run a fresh scoped deployment using `v1.52.4` and verify that a newly emitted
key reaches dashboard registration without manual sweep. Do not delete the
existing fleet until that canary is captured.
