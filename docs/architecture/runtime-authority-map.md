# Runtime Authority Map

## Authority order

1. **DB logical/provider row** — canonical ownership, lifecycle, account, worker,
   generation, and policy state.
2. **Exact generation/device/proxy CAS tuple** — permits a runtime mutation only
   when the caller proves it is acting on the current assignment.
3. **Worker inventory** — authoritative for what the worker currently reports
   running, subject to authenticated heartbeat freshness.
4. **Provider dashboard** — external observation of provider acceptance, online
   state, country, usage, or ban state.
5. **Collector snapshot** — external earnings/payment/device observation, useful
   for reconciliation but never a replacement for ownership authority.

## Split-brain handling

- DB says the node exists but inventory omits it: mark stale and follow the
  declared recovery hold; do not immediately delete or reassign a proxy.
- Inventory reports an unknown runtime: record an orphan observation and require
  an explicit adoption path; never blind-adopt it into production ownership.
- Provider dashboard disagrees with worker inventory: preserve DB assignment,
  record the external observation, and run the provider-specific health policy.
- Collector disagrees with dashboard or DB: retain both observations with
  timestamps; do not rewrite identity, lease, or payment ownership from a single
  collector response.
- A generation/device/proxy mismatch is a stale mutation. Reject it with CAS
  failure and re-read authority before retrying.

## Provider-specific authority overlays

EarnApp account ownership and serialized link operations remain account-scoped;
Pawns/IPRoyal proxy admission remains provider-private and honors `ip_used`;
MYST/NKN remain direct-only. These overlays refine lifecycle decisions but do not
invert the authority order.

## Unverified migration behavior

The migration worktree adds reconciliation, staged recovery, proxy-health, and
network-audit code relative to `origin/main`. Those changes are not authority
until classified, reviewed, tested, and curated in a later phase.
