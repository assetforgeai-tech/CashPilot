# Pre-live findings — 2026-09-10/11

## Fixed during this audit

1. Windows development/install reproducibility: `uvloop` is now excluded on
   Windows through a platform marker; lock/export files and a regression test match.
2. Shipped compose drift: `docker-compose.yml` and `docker-compose.fleet.yml`
   now pin UI and worker images to release series `1.32`, matching the newest fork
   tag discovered by the release-drift test.
3. Security scanner false-positive clarity: the RFC 6455 WebSocket SHA-1 use is
   explicitly marked protocol-only with `usedforsecurity=False`; Bandit now has no
   HIGH-severity result.
4. Fork-link drift: the sidebar, README badges, and Codecov link pointed to the
   upstream project; they now point to `assetforgeai-tech/CashPilot` with a
   regression test.

## Verified

- Sticky EarnApp egress ownership and capacity counters exist and have prior live
  production evidence.
- Wipter migration implementation and reconciliation alias have regression coverage;
  post-fix DNS packet proof remains a separate gate.
- Security/auth/CSP/frontend regression subset: `248 passed`.
- Provider-network regression subset: `30 passed`.
- Public 4gmt HTTP smoke: `/`, `/settings`, `/proxy-pool`, and `/fleet` respond
  `200` with the expected unauthenticated sign-in shell; no protected data was
  exposed.
- Dependency audit from `requirements.txt`: `pip-audit` reported no known
  vulnerabilities.

## Still unverified or incomplete

- Chrome profile 40 full UI/UX interaction sweep, screenshots, and input testing.
- Wipter post-DNS packet capture, IPv6, UDP/WebRTC, and reboot persistence proof.
- Provider-wide network matrix for NKN, earnfm, iproyal, Mysterium, PacketStream,
  Proxies-SX, Proxybase, ProxyRack, Repocket, Spide, Traffmonetizer, Uprock,
  URnetwork, and any active runtime not present on the audited worker.
- Shared lifecycle helper wiring into every provider scheduler/adapter.
- PayPal pool live assignment, auto-redeem, quarantine, and deletion verification.
- Real account-pool adapters for providers other than EarnApp.
- EarnApp token expiry extraction and manual-login-gated auto-import live proof.
- Provider lifecycle/network matrix: see `docs/evidence/provider-lifecycle-network-matrix-2026-09-11.md`.

## Live-test decision

`BLOCKED_FOR_READINESS`: do not start live canary from this audit result. The block
is evidence-based, not a provider runtime failure: browser evidence and fleet-wide
network proof are missing, and PR/release rollout has not yet been verified.
