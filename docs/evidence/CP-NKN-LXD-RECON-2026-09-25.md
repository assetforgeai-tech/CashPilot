# NKN LXD provider-state reconciliation — 2026-09-25

## Scope

- Fix server heartbeat reconciliation for NKN runtimes hosted by the worker's
  LXD helper.
- Keep wallet CAS, worker identity, provider node identity, and lease semantics
  unchanged.
- No provider credential, proxy, wallet, node, or Azure resource mutation in
  the implementation worktree.

## Root cause

The worker reports NKN LXD runtimes under `provider_states.nkn.instances`.
Generic reconciliation only compared `provider_instances` with the Docker
`containers` list. LXD guests are intentionally absent from that list, so all
20 live NKN rows were marked `missing_once` even though the 20 NKN wallets were
still `LEASED` and runtime heartbeats continued.

## Change

- Map only CAS-confirmed NKN `slot_id` values to the server-scoped
  `nkn-direct-w<worker_id>-<slot_id>` bookkeeping ID.
- Never trust a client-supplied NKN instance ID for generic reconciliation.
- Ignore malformed slot IDs.
- Mark a previously guarded NKN row `running` only when its wallet CAS succeeds
  and LXD evidence reports `running=true`.
- Preserve the existing `missing_once`/recovery hold and lease release rules for
  all other providers.

## Tests and gates

Commands run from the task worktree:

```text
python -m pytest -q
3594 passed, 7 skipped

uv run ruff check .
All checks passed!

uv run ruff format --check .
567 files already formatted

python -m compileall -q app tests
PASS

git diff --check
PASS

secret scan (app/tests/docs evidence)
no matches
```

Focused NKN/provider suites: `59 passed` before the final guard regression
test; the full suite above includes the final test set.

## Production observation and safe guard

Before the fix was released, the production VM was inspected read-only through
Azure RunCommand because the NSG allowed SSH only from registered admin IPs.
Observed state:

- VM: `cashpilot-prod-ea`
- Subscription: `a9d21cd7-abf8-4b14-a2e5-1867178fd5f6`
- RG: `RG-CASHPILOT-PRODUCTION-EASTASIA-20260924`
- worker heartbeat: online
- NKN wallets: `20 LEASED`
- NKN provider rows: `20 missing_once`
- no proxy pool, active proxy lease, MYST wallet, EarnApp account, or provider
  account rows available in the new production database

After verifying a recent worker heartbeat, exactly 20 expected NKN rows, and 20
leased wallets, a transaction moved only those rows from `missing_once` to
`verification_pending` so the one-hour cleanup hold could not delete live
bookkeeping before the release fix. SQLite backup created before the guard:

```text
/data/cashpilot-nkn-row-guard-20260925T0149Z.db
```

No wallet, provider node, runtime identity, proxy, or VM was deleted or
reassigned.

## Remaining gate

This evidence is code/reconciliation evidence only. The PR must pass CI and be
merged; the resulting immutable release must be deployed to `cashpilot-ui`,
then the 20 NKN rows must be rechecked for `running`, with 20/20 heartbeat ACK
and wallet lease evidence. Provider lanes remain blocked until their real pool
credentials/runtime inputs exist in the new production control-plane.
