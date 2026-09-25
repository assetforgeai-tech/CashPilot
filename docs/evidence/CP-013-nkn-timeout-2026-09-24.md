# CP-013 NKN LXD timeout and lease safety — 2026-09-24

## Production finding

Scope: subscription `a9d21cd7-abf8-4b14-a2e5-1867178fd5f6`, RG
`RG-CASHPILOT-PRODUCTION-EASTASIA-20260924`, VM `cashpilot-prod-ea` only.
No other VM, provider account, proxy, wallet material, or Azure resource was changed.

PR #506 merged as `28444424`; Auto Release `v1.68.2` and its immutable
manifest passed. Only `cashpilot-worker` was recreated with digest
`sha256:557f766affc98dfd942eacedf6c506ee387b056c0dde18134f4606cc8dc9b37f`.
Image, health, canonical mount set, unchanged UI, and unchanged provider
container set passed. The old worker digest remains the rollback pin.
The first worker rollout rejected an ordering-only mount comparison and
rolled back successfully. The second used a sorted semantic mount comparison
and passed. The persistent VM compose pin was updated; `/data`, `/fleet`,
public-IP slots, worker identity, and UI were preserved.

After more than 18 minutes, 13 NKN LXD instances stayed RUNNING. All 13
assignment journals retained a recent server ACK, with no suspension.
The server had 20 NKN wallets, 13 leased and seven available before retry.
Proxy Pool, Myst wallet pool, and EarnApp account pool were empty; the only
stored provider setting was the NKN beneficiary. Generic auto-deploy was off.

One authorized NKN scheduler retry exposed a separate defect. The server
waited 60 seconds for an ordinary LXD deploy while the worker's restricted
LXD helper can take up to 900 seconds. The timeout was classified as failure,
releasing the wallet while the helper was still creating its node. Wallet 14
was successively assigned to several slots before the request was stopped.
The UI was restarted to stop the batch. Its health and unchanged mounts were
verified. The helper then removed LXD instances with stale CAS metadata.
Final inspection found 14 leased wallets and 14 matching RUNNING LXD instances;
wallet 14 is assigned to `ipv4-009`. Six wallets remain available. The
retry did not achieve the 20-node target. No NKN node or wallet was manually
deleted, and no provider outside NKN was deployed.

## Code change and gates

The ordinary NKN LXD worker call now waits 900 seconds, matching the helper's
maximum request timeout. After the request is dispatched, every response/error
preserves the slot's CAS wallet lease: even a 400 response can arrive after
the helper has started mutating LXD. Only failures proven before dispatch may
release the lease. A retry can use the same wallet/slot instead of handing it
to another slot.

- RED tests: ordinary LXD call lacked `timeout=900`; worker 503 released the
  wallet. Both failed for the expected reason before implementation.
- Focused NKN suites: 45 passed after the timeout change.
- Full suite after both changes: 3589 passed, 7 skipped.
- Ruff check/format, compileall, and `git diff --check`: pass on changed files.

## Remaining gates

- Merge the timeout/lease fix with green CI, publish immutable release/manifest,
  update only `cashpilot-ui`, and verify DB/key/mount/worker preservation.
- Reconcile the 14 existing LXD identities with DB rows before another deploy.
  Never release wallet 14 or repurpose its slot by inference.
- Retry the remaining six slots one at a time; inspect worker response, CAS,
  LXD status, egress, heartbeat, and dashboard after each.
- Provider proxy lanes need real Proxy Pool capacity and scoped provider
  runtime input; Myst needs wallet material. Do not fabricate credentials or
  silently reduce the requested 20-node cardinality.
