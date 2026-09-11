# Pre-live requirements traceability — 2026-09-11

| Requirement | Evidence | Status | Remaining action |
|---|---|---|---|
| Backend regression | Full pytest `2777 passed, 8 skipped` | pass | Rerun on audit commit |
| Static lint/compile | Ruff, `compileall`, `git diff --check` | pass | Rerun on audit commit |
| Dependency/security scan | `pip-audit` requirements scan; security tests | pass/partial | Run CI-equivalent scan on release commit |
| Auth/secret safety | `61` security/auth tests; `12` no-credential tests | pass | None in current scope |
| EarnApp lifecycle | Scheduler/source review + `207` canary contract tests | partial | Live worker reconciliation |
| Other-provider lifecycle | Provider matrix | unverified | Adapter-specific verification or explicit exclusion |
| Proxy lease/account ownership | DB constraints/source review | partial | Live DB vs dashboard reconciliation |
| DNS/proxy zero-leak | EarnApp/Wipter evidence | partial | Packet capture + reboot per active runtime |
| UI navigation/controls | Static inventory, 14 templates/168 controls | unverified | Chrome profile 40/CDP interaction sweep |
| Token expiry/import | Source paths only | unverified | Controlled live token expiry/import test |
| PayPal pool | Foundation/source paths | unverified | Live assignment, auto-redeem, delete/quarantine test |
| GHCR images | CI build/publish workflow; compose tags | partial | `read:packages` token + manifest digest check |
| Release integrity | PR #246 checks pass on `efe4ce1` | partial | Include audit commit, rerun CI, release |
| Production live canary | No mutations during audit | blocked | Requires all applicable gates above |

## External prerequisites

1. Chrome profile 40 exposed through the approved connector/CDP path without killing the current session.
2. Read-only worker diagnostic window for packet capture and reboot evidence.
3. GitHub token with `read:packages` for GHCR manifest verification.
4. Explicit authorization to commit/push audit changes and release after CI passes.

## Decision rule

`production-ready` requires every in-scope row to be `pass` or explicitly accepted
as `unverified` by the owner. `partial`, `blocked`, or unreviewed external flows
cannot be silently promoted to pass.
