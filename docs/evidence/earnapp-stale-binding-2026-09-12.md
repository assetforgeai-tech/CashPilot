# EarnApp stale binding evidence - 2026-09-12

- Worker `43406` runs `ghcr.io/assetforgeai-tech/cashpilot-worker:1.33.1` and reports healthy heartbeats.
- `earnapp-prod-ubuntu-20260901-01` had a pending binding journal for proxy `13895`, while the server database had no `ACTIVE` reservation.
- The main container was present, but its managed `-egress` sidecar was absent. This caused repeated `proxy/finalize` HTTP `409` responses during reconciliation.
- In-place restart preserved logical node, device identity, generation, and proxy assignment. No node deletion, remote unlink, proxy release, or rotation was performed.
- After restart, the container still starts only `redsocks`; repeated TLS `unexpected eof` confirms the missing egress route is an operational runtime failure, not proof of an EarnApp account failure.
- Commit `ea8524f` makes clean main-only rollback idempotent and adds regression coverage; deployment remains gated by PR approval.
