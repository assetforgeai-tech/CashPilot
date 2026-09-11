# Production-readiness progress — 2026-09-11

## Fresh verification

- Local test suite: `2794 passed, 8 skipped` in 219.55 seconds.
- `python -m compileall -q app tests`: passed.
- `python -m ruff check app tests`: passed.
- `git diff --check`: passed.
- `pip-audit -r requirements.txt`: no known vulnerabilities reported for the locked CashPilot requirements. The audit environment reported two private/local packages as not found on PyPI; this is not treated as a vulnerability.
- Bandit completed with no high-severity findings. Its medium/low output contains intentional dynamic SQL over internally allowlisted identifiers, fixed provider URLs, temporary bundle paths, subprocess wrappers, and the existing EarnApp emulation contract; these require code-level review before changing.

## Production snapshot

- UI image: `ghcr.io/assetforgeai-tech/cashpilot:1.32.9`, healthy.
- Worker image: `ghcr.io/assetforgeai-tech/cashpilot-worker:1.32.0`, healthy and unchanged.
- Live UI container exposes port `8080`; unauthenticated `/settings` redirects to `/login`.
- Security headers observed on the direct HTTP redirect: `X-Content-Type-Options`, `X-Frame-Options`, `Permissions-Policy`, CSP, and `Referrer-Policy`. HTTPS-edge `Strict-Transport-Security` remains unverified from this host.
- Live DB snapshot: `workers=4`, `provider_instances=50`, `proxy_endpoints=1254`, `provider_proxy_leases=199`, `earnapp_accounts=4`, `earnapp_logical_nodes=85`, `earnapp_account_egress_ownership=20`, `earnapp_paypal_pool=1`, `earnapp_account_snapshots=1292`.
- SQLite integrity: `ok`; foreign-key errors: `0`.

## PayPal Pool

- Live container template contains the input `earnapp-paypal-destination`, the `Add PayPal` action, and the masked pool list under `Settings -> EarnApp Account Pool -> PayPal Pool`.
- Source and live route are present. Interactive Chrome verification remains `blocked` because the user's Chrome CDP connector is unavailable in this session; this is not evidence that the control is absent.
- If the control is not visible in a browser, force reload `/settings` with `Ctrl+F5`, then verify the `EarnApp Account Pool` section. No live destructive action was performed.

## Gate status

| Area | Status | Evidence / gap |
|---|---|---|
| Core tests and static checks | verified | Fresh commands above |
| Live UI deployment and DB integrity | verified | Live container and DB snapshot above |
| PayPal input markup/API foundation | verified | Source + live container inspection |
| PayPal external assignment/auto-redeem/quarantine | unverified | Requires controlled real EarnApp account mutation |
| Chrome profile 40 UI/input sweep | blocked | CDP/connector unavailable |
| Fleet-wide proxy/DNS/IPv6/UDP leak proof | unverified | Packet capture + reboot evidence missing for most providers |
| Provider-wide lifecycle normalization | unverified | EarnApp adapter is covered; other providers remain adapter-specific |
| Token auto-import live proof | unverified | No authenticated Chrome-profile evidence |

No completion claim is made until the remaining gates have authoritative evidence.

## PayPal input fix and UI-only release

- PR #265 merged as `a5d3435` after CodeQL, tests, and lint passed.
- Release `v1.32.14` published; UI and worker image tags resolved and embedded
  version checks passed.
- `cashpilot-ui` redeployed alone to digest
  `sha256:f30f2a0d9588c5e6130f8586f15b8dd4a125cb10bbda4d339097d0af6ca07f38`;
  it reports `CASHPILOT_VERSION=1.32.14`, healthy, restart count `0`.
- `cashpilot-worker` remains image `1.32.0`, same container ID/start time,
  healthy, restart count `0`.
- PayPal pool input and account payment-modal input now have distinct DOM IDs.
  Collector snapshots read `redeem_details` from the authenticated `/money`
  payload, matching the EarnApp dashboard contract instead of the legacy
  standalone endpoint.
- Targeted EarnApp/payment/UI suite: `84 passed`; Ruff and diff checks passed.
- Live DB after redeploy: SQLite integrity `ok`, foreign-key errors `0`,
  PayPal pool `1` total / `1` assigned. Account `2` has configured PayPal
  payment with masked destination; no raw payout address was printed.

## Current regression sweep

- Full suite after the release changes: `2800 passed, 8 skipped` in `226.63s`.
- The suite includes EarnApp account deletion confirmation, sticky egress
  ownership, PayPal pool assignment/quarantine, payment readback, UI markup,
  lifecycle decisions, and provider capacity contracts.
- Remaining unverified gates are external-observation gates only; no failing
  source regression is currently known.

## Follow-up fix and live verification

- PR #262 fixed a false-positive network audit: EarnApp's current contract is
  main-container Redsocks + DNS forwarding + fail-closed iptables, not a
  required sidecar.
- PR #262 passed CI and merged; release `v1.32.11` published.
- `cashpilot-ui` redeployed alone to `v1.32.11`; it is healthy with restart
  count `0`.
- `cashpilot-worker` remains `v1.32.0`, same container ID/start time, healthy,
  restart count `0`.
- Live provider-network reconciliation now reports EarnApp `pass` on the
  confirmed worker with no missing sidecars or untracked runtimes. Workers
  without confirmed inventory remain `unverified`.
- Live EarnApp reconciliation reports no missing or untracked instances on
  workers with confirmed inventory.
- Full regression suite after the reconciliation fix: `2798 passed, 8
  skipped`.
