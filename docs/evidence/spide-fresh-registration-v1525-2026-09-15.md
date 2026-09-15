# Spide fresh registration verification

Captured 2026-09-15 after release `v1.52.5`.

## Change under test

The dashboard registration request now matches the tested raw flow: form-
encoded body, explicit `Content-Type`, `X-Requested-With`, and the existing
bearer/cookie authentication header.

## Fresh canary

- Target: `spide-direct-w118903-ipv4-001` on Azure worker `118903`.
- Deployment response: HTTP `200`, `status=deployed`, `failed=0`.
- Runtime container: running.
- The post-deploy automation emitted a Device key and registered it without
  manual dashboard interaction.
- Dashboard API: matching Device key hash found, `status=online`.
- Device key and account credentials are intentionally not recorded.

## Verification

- Focused tests: `48 passed`.
- Ruff: clean.
- `git diff --check`: clean.
- Worker images: `ghcr.io/assetforgeai-tech/cashpilot-worker:1.52.5`, healthy
  on both Azure workers; worker identity/data/provider IDs preserved.
- Server UI: `ghcr.io/assetforgeai-tech/cashpilot:1.52.5`, healthy; SQLite
  integrity check passed during rollout.

## Remaining gates

This proves Spide fresh registration only. NKN durable-state reconciliation,
full network matrix, reboot/lifecycle proof, and clean cycle 2 remain open.
