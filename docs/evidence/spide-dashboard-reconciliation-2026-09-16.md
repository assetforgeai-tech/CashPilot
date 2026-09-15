# Spide dashboard reconciliation (2026-09-16)

The server-side Spide adapter authenticated with the configured account and queried the provider device-list endpoint successfully (HTTP 200 across pages 1-8).

- Dashboard devices returned: `45`.
- Dashboard devices reported online: `38`.
- CashPilot provider rows for the two authorized Azure workers: `40` Spide rows (20 per worker: 10 direct and 10 proxy).
- All 40 corresponding worker containers were running at the check.
- CashPilot health events repeatedly recorded `spide/check_ok` during the preceding hour.

The CLI emits periodic `Status: OK` but does not repeat its `Device key` after startup. Therefore the current evidence proves provider API reachability, runtime liveness, and aggregate reconciliation, but cannot prove a one-to-one local-container/device mapping without a provider-side stable identifier endpoint or a startup log capture.

No dashboard collector is installed or executed in any Spide container.
