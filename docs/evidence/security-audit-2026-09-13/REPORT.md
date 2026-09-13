# Security Audit - 2026-09-13

## Scope

Provider topology, proxy leasing, EarnApp qualification, lifecycle dispatch, and
browser-facing provider detail UI in this worktree.

## Result

One confirmed TLS trust defect was found and remediated before this report:
the EarnApp WebSocket qualification probe disabled certificate and hostname
verification. A proxy or MITM could forge a `CID_SET` response, which the
server persisted as eligible evidence and later used for EarnApp leasing.

The current implementation uses the platform trust store with
`CERT_REQUIRED` and hostname verification for `proxyjs.brdtnet.com`. Regression
coverage is in `tests/test_earnapp_proxy_probe.py`.

No other exploitable injection, authorization bypass, secret disclosure,
CSRF, redirect, or client-side issue was confirmed in this pass. Live network
leakage remains a deployment verification item, not a source-only claim.

## Hardening Notes

- Keep proxy lanes fail-closed with no direct fallback.
- Keep Pawns/IPRoyal `ip_used` masks provider-scoped.
- Keep EarnApp node-health recovery isolated from generic providers.
- Re-run this audit after enabling production integrations or changing trust
  stores.
