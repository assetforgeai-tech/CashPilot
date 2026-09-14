# EarnApp provider-dashboard audit

Date: 2026-09-14

Source: authenticated browser session, EarnApp Passive Income page.

Observed:

- Lifetime/current balance: `$9.095`.
- Earnings update countdown: approximately `38min` at capture time.
- Auto-redeem destination: PayPal.
- Devices table exposed device ID, country, usage, rate, and amount.
- Observed rows included VN devices with non-zero usage and amounts, plus one
  iOS row at `0s` / `$0`.

Artifacts:

- `earnapp-provider-dashboard-20260914.txt`
- `earnapp-provider-dashboard-20260914.png`

Boundary: this proves the authenticated account dashboard is reachable and
reports usage/earnings. It does not map these device IDs to the two Azure
workers, and therefore is not fresh Azure canary proof. Azure production
evidence still requires a controlled node-to-dashboard identity mapping and a
post-cycle usage/balance delta.
