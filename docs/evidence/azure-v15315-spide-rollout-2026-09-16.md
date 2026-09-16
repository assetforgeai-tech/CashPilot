# Azure worker v1.53.15 Spide rollout (2026-09-16)

Scope: Azure workers `118903` (`20.187.79.110`) and `118904`
(`20.210.93.220`). No test-sing or test-us worker was touched.

Both workers were upgraded to
`ghcr.io/assetforgeai-tech/cashpilot-worker:1.53.15` using a worker-only
Compose override. The check preserved the `/data` volume, `.worker_id`,
`.worker_key`, and all provider container IDs on each worker. Both workers
reported `running|healthy` after the upgrade.

Post-upgrade Spide read-only check found 20 Spide containers per worker (10
direct and 10 proxy). Recent logs for every sampled runtime ended in
`Status: OK`. No provider container was recreated by the rollout.

This proves worker image rollout and Spide runtime continuity. It does not
prove provider dashboard earnings or explain an unobserved HTTP 500; those
still require a concrete provider response/request trace.
