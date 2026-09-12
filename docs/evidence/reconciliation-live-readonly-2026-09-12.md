# Live reconciliation read-only — 2026-09-12

Authenticated API inspection completed without mutation.

- EarnApp reconciliation returned `6` worker reports.
- Provider-network reconciliation returned `5` scoped reports.
- EarnApp worker `92161`: `pass`, no missing sidecars/untracked entries.
- EarnApp worker `43406`: `unverified`; no explicit findings, but no passing
  runtime proof.
- NKN worker `43406`: `unverified`.
- Wipter worker `3113`: `pass`, no missing sidecars/untracked entries.
- Wipter worker `90241`: `unverified`.

Detailed EarnApp reconciliation: worker `92161` has `2` DB/reported
instances with `inventory_confirmed=true`; workers `112494` and `112444` have
no tracked instances and are confirmed empty. Worker `43406` has `18` DB and
reported instances with no missing/untracked rows, but
`inventory_confirmed=false`; this remains unverified rather than being treated
as healthy.

`unverified` is retained where the API lacks positive runtime evidence; it is
not promoted to `pass` from an empty findings list.
