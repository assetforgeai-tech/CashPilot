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

`unverified` is retained where the API lacks positive runtime evidence; it is
not promoted to `pass` from an empty findings list.
