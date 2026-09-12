# EarnApp/PayPal read-only verification — 2026-09-12

Authenticated Chrome `Profile 40` API inspection completed without mutation or
secret export.

- EarnApp accounts: `2`, both `ACTIVE`; both expose cookie-backed expiry metadata.
- Account rows report token warnings (`expires_within_7d` and `expires_within_24h`).
- Active nodes: `19`; recovery-hold nodes: `0`.
- EarnApp proxy capacity: `318` eligible, `310` leaseable/ready, `7` used/occupied,
  `8` sticky-owned.
- Recovery hold is `3600` seconds.
- PayPal pool: `1` destination; assignment is currently unassigned; destination
  remains masked.

This verifies API/UI readback only. Assignment, auto-redeem, quarantine, token
refresh, and suspension/release mutation scenarios remain unverified.
