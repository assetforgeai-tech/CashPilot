# Security review — 2026-09-10/11

## Scope

High-confidence review of FastAPI routes, database access, subprocess/SSH paths,
collectors, Docker orchestration, static JavaScript, CI manifests, and secret
handling. Test files and user `.tmp-*` artifacts are excluded from findings.

## Result

No high-confidence exploitable vulnerability identified in the reviewed paths.

## Controls verified

- SSH publisher host and port are validated; the configured SHA-256 host key is
  required and checked before authenticated commands.
- SSH commands use argument arrays, bounded timeouts, strict host-key checking,
  and no shell interpolation.
- Publisher private keys/wallet material are handled in memory or protected files;
  API responses redact credential material.
- Frontend interpolations reviewed in the audited paths use `escapeHtml`; CSP and
  security-header tests pass.
- Proxy and lifecycle mutations use authenticated, guarded routes and CAS-style
  ownership checks.
- Compose images are explicit fork GHCR tags, not `latest`; pins now track `1.32`.
- Bandit findings were reviewed. The reported SHA-1 is the WebSocket protocol's
  required `Sec-WebSocket-Accept` calculation, subprocess findings use fixed
  argument arrays, and the temporary publisher path is owner-controlled with
  mode `0700` plus cleanup. None is a high-confidence attacker-controlled exploit.
- The protocol hash now passes `usedforsecurity=False`; the targeted EarnApp
  probe suite passes and Bandit reports no HIGH-severity findings.

## Verification items still open

- Full browser-profile sweep is unavailable because the connector returned
  `Codex auth token is unavailable`.
- Provider-wide live packet/reboot evidence is incomplete; unknown providers remain
  `unverified`.
- `pip-audit --locked .` could not run because the installed pip-audit version
  does not recognize `uv.lock` as a supported lockfile; no vulnerability result
  is claimed. CI dependency/security checks remain authoritative.

## 2026-09-11 follow-up

- Credential-pattern sweep found only test fixtures and environment-variable placeholders in preserved runtime artifacts; no committed production credential was identified.
- Secret/auth/security regression subset passed (`61 passed`); no-credential suite passed (`12 passed`).
- EarnApp MacOS/iOS deliberately set `NODE_TLS_REJECT_UNAUTHORIZED=0`. The source comment now states the actual boundary: fail-closed proxy routing prevents direct egress but does not authenticate the upstream TLS peer. Runtime behavior was not changed during the audit.
- EarnApp canary contract suite passed (`207 passed`) after the documentation correction.
