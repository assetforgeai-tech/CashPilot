# Production rollout evidence - 2026-09-11

## PayPal Pool UI

- Release `v1.32.2` published from merge `b3c700e`.
- `cashpilot-ui` redeployed alone on the server to `ghcr.io/assetforgeai-tech/cashpilot:1.32.2`.
- UI container is `running|healthy`; SQLite `integrity_check=ok`.
- PayPal Pool is outside the payment modal and exposes the email input, Add PayPal action, and masked pool list.
- Authenticated PayPal Pool API returned HTTP 200 with one masked item.

## Test-US worker rollout

- Worker upgraded in place from `1.24.5` to `ghcr.io/assetforgeai-tech/cashpilot-worker:1.32.2`.
- Worker is `running|healthy`, restart count `0`.
- Existing EarnApp containers were not recreated: all three observed container IDs were unchanged.
- Systemd fallback was updated from `docker-compose.worker.v1.21.24.override.yml` to `docker-compose.worker.v1.32.2.override.yml`; reboot fallback therefore cannot silently downgrade the worker.

## Server reconciliation snapshot

- Database integrity: `ok`.
- Foreign-key violations: `0`.
- Workers `43406` and `92161` reported `online` with fresh heartbeats.
- EarnApp logical-node records retain account, platform, generation, device, proxy, worker, and health fields.
- Several historical rows are `PLANNED`, `RECOVERABLE`, or `verification_pending`; they are intentionally not deleted during audit. Cleanup requires an explicit reconciliation policy and destructive confirmation.

## Remaining gates

- Live Chrome profile 40 interaction remains unavailable because the browser connector/CDP endpoint is not exposed.
- PayPal assignment, auto-redeem, account deletion, and quarantine still lack a live mutation test.
- Fleet-wide packet capture/reboot evidence for every provider remains incomplete.
- Main post-merge Tests workflow was cancelled after hanging in `Run tests`; release verification independently passed its full test gate.
