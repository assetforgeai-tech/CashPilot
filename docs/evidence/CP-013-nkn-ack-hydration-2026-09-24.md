# CP-013 NKN ACK hydration fix — 2026-09-24

## Finding

The production worker received authenticated NKN assignment ACKs, but the
heartbeat path then ran LXD inventory recovery. Inventory recovery rewrote an
existing local journal for the same `(slot_id, wallet_id,
wallet_assignment_version, lease_client_id)` assignment. The rewrite removed
`last_server_ack_at`, so the local lease guard treated the assignment as stale
and suspended it again on the next cycle.

Observed live symptoms before the fix:

- Worker and UI healthy; worker heartbeat HTTP 200.
- NKN heartbeat ACK count remained partial (`13`) while 13 leased slots were
  repeatedly suspended after the local ACK deadline.
- Matching LXD runtimes were stopped fail-closed; no wallet, volume, lease, or
  provider row was deleted.

## Change

`_hydrate_nkn_lxd_states` now hydrates only when the local journal is absent or
does not match the exact server CAS identity. A matching journal is preserved,
including its ACK timestamp and suspension guard. CAS identity requirements are
unchanged.

## Verification

- RED regression reproduced the journal overwrite and failed as expected.
- Focused NKN suites: `50 passed`.
- Full suite on clean `origin/main` base: `3585 passed, 7 skipped`.
- `uv run ruff check .`: pass.
- `uv run ruff format --check .`: pass.
- `python -m compileall -q app tests`: pass.
- `git diff --check`: pass.

## Runtime boundary

No Azure, SSH, worker, LXD, provider, proxy, wallet, lease, or production
mutation was performed by this code change. Live rollout requires a new
immutable worker image and a separate staged worker restart/verification.
