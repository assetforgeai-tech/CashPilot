# NKN lease ACK diagnostic (2026-09-16)

## Observed behavior

- Azure worker `118903` returned authenticated heartbeat HTTP `200`.
- Its worker log recorded repeated `Could not apply NKN lease ACK ...: RuntimeError`
  and then suspended slots after the local 14-minute ACK deadline.
- The server database still showed the leases as `LEASED`, while several runtime
  rows were `stopped`; this is an ACK/runtime reconciliation failure, not a
  ChainDB or Spide artifact issue.

## Safe diagnostic change

`app/worker_api.py` now records the bounded local exception detail (single line,
maximum 240 characters) when ACK application fails. It does not log wallet JSON,
passwords, tokens, or the full response payload. A regression test covers the
diagnostic path.

## Verification

- Focused NKN sync tests: `14 passed`.
- Full suite: `1647 passed, 8 skipped`.
- Ruff: clean.

The diagnostic change is source-only. No live NKN lease, provider identity, or
container was deleted or redeployed. A matching worker image release is required
before the new detail appears in Azure logs.
