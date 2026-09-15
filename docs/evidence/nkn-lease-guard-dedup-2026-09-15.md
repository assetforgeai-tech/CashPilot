# NKN lease-guard deduplication

## Finding

On Azure worker `118904`, the same six assignments were logged as suspended on
every heartbeat after the first failed ACK deadline. The local state already had
`lease_guard_suspended=true`, so repeated suspend calls added no safety and hid
the original ACK/reconciliation failure.

## Change

`_enforce_nkn_lease_guard` now skips assignments already marked
`lease_guard_suspended`. A valid server heartbeat ACK with the exact
`slot_id`, `wallet_id`, `wallet_assignment_version`, and `lease_client_id`
still clears the flag and resumes the matching runtime.

## Verification

- Regression tests: `120 passed` across NKN host helper, LXD runtime, worker
  synchronization, Spide catalog, and automation suites.
- No Azure runtime rollout performed in this step; the worker-side patch must
  be included in the next versioned image rollout before claiming live effect.
