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
