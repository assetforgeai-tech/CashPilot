# CashPilot UI/UX browser sweep — 2026-09-12

Authenticated inspection completed through an isolated Chrome `Profile 40`
CDP session bound to `127.0.0.1:9227`.

## Surfaces captured

`Dashboard`, `Setup Wizard`, `Service Catalog`, `Payouts`, `Proxy providers`,
`Proxy pool`, `MYST Wallet`, `NKN Wallet`, `Settings`, and `Fleet`.

Each surface has a full-page PNG and text snapshot in this directory. All
navigation targets returned the expected CashPilot page title and remained
authenticated.

## Findings

- No navigation or authentication failure observed.
- Destructive controls were not activated.
- PayPal/account controls require a dedicated interaction pass; no mutation
  was performed.
- Responsive, keyboard, validation, and live provider behavior remain
  `unverified`; screenshots alone do not prove those requirements.
- No secret values were exported or written to evidence.

## Proxy Pool live reconciliation

The authenticated API snapshot contains `1,254` rows: `1,002` alive and
`252` dead. All `1,002` alive rows have an egress IP, country metadata, and a
non-unknown IP type. The `252` unresolved/unknown rows are dead rows whose
generic check failed; they are not live metadata failures. The summary query
was corrected to count metadata pending and unknown IP type only for alive
rows. Regression coverage passed.
