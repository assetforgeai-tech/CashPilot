# Spide Azure verification

Captured 2026-09-15 against the production Spide account and the two Azure workers.

## Dashboard authority

The authenticated Spide endpoint `GET /api/v1/device/list/{page}` returned 40 devices across eight pages. Every returned device had `status=online`. The current fleet contains 20 direct and 20 proxy instances, identified by the CashPilot deployment title convention and worker inventory.

Device keys are intentionally not recorded. Runtime keys were compared to dashboard registrations using SHA-256 digests only; all 40 runtime keys matched a dashboard device digest.

## Runtime authority

Both workers reported 20 Spide service containers (10 direct, 10 proxy), excluding egress sidecars. The latest log probe for every service container ended with `Status: OK`.

## Registration contract

CashPilot follows the raw working flow: login form, official CLI `Device Key`, then form-urlencoded device registration. Repeated registration returns `Device is already registered`; CashPilot treats that response as idempotent success.

## Remaining proof

Online status and registration are proven. Spide earnings/statistics still require a separate dashboard statistics capture before marking earnings as production-proven.
