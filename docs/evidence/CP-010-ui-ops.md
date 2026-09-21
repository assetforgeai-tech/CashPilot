# CP-010 UI Operations Audit

Date: 2026-09-21
Baseline: `origin/main` at `1c4db8bfcb850987c0b8517a31dccdbf4a69f399`
Mode: static, read-only UI and API contract review. No browser session or production action was used.

## Result

`FAIL` against the production-operations UI contract. Destructive confirmation is inconsistent and four workflows still use blocking browser prompts. Fixes belong to CP-005 or separate focused UI tasks; CP-010 made no implementation changes.

## Findings

### MEDIUM - Sensitive and destructive workflows still use `window.prompt`

- Evidence: guarded NKN wallet release uses `prompt()` at `app/static/js/app.js:2063`; locked EarnApp account deletion uses two `window.prompt()` calls at `app/static/js/app.js:3921` and `app/static/js/app.js:3926`; replacement-ticket worker selection and one-time secret display use `window.prompt()` at `app/static/js/app.js:3944` and `app/static/js/app.js:3956`.
- Operational impact: browser prompts cannot show structured scope, affected resources, rollback guidance, validation state, or accessible error context. The one-time replacement ticket is displayed in a generic prompt with no explicit expiry/copy-state treatment beyond its message.
- Contract conflict: CP-005 explicitly prohibits `window.prompt` and requires modal confirmation for destructive operations.
- Fix task: replace prompts with accessible application modals; show immutable target identity, consequences, typed confirmation, pending state, server rejection, success, expiry, and copy acknowledgement.

### MEDIUM - Destructive confirmation strength is inconsistent

- Evidence: deleting the entire proxy inventory has two confirmations plus a server phrase at `app/templates/proxy_pool.html:545` through `app/templates/proxy_pool.html:557`; removing a worker has one `confirm()` at `app/templates/fleet.html:560` through `app/templates/fleet.html:568`; removing a service is dispatched through the generic UI action path and relies on browser confirmation rather than a shared destructive-action component.
- Operational impact: equally consequential actions present different target detail and acknowledgement strength. Operators can remove the wrong worker or service while duplicate/stale identities are present; the UI itself documents that ambiguity near `app/templates/fleet.html:560`.
- Fix task: one shared modal contract, severity tier, exact target identifier, affected worker/provider/storage, rollback limits, typed phrase for irreversible state loss, and disabled submit while pending.

## Verified Controls

- Owner-only UI/API gates protect deployment, credential mutation, worker deletion, fleet-key reveal, and canary operations; examples: `app/main.py:4048`, `app/main.py:8251`, `app/main.py:9691`, `app/main.py:9899`.
- Fleet key is not returned by the status endpoint; reveal is a separate owner-only POST and audit log: `app/main.py:9888` through `app/main.py:9904`.
- Critical-volume deletion escalation is owner-only: `app/main.py:5386` through `app/main.py:5397`.
- Provider-supplied UI values are commonly passed through `escapeHtml`, while nonce CSP and `frame-ancestors 'none'` reduce injection and clickjacking impact: `app/main.py:2857` through `app/main.py:2867`.
- Proxy-pool total deletion uses a server-checked phrase in addition to client confirmation: `app/templates/proxy_pool.html:545` through `app/templates/proxy_pool.html:557`.

## Coverage

- Reviewed navigation/action wiring, destructive controls, loading/error feedback, worker removal, service lifecycle, proxy-pool deletion, credential clearing, EarnApp account deletion, wallet release, replacement tickets, and fleet-key reveal.
- Dynamic screenshots, keyboard navigation, focus trapping, screen-reader labels, and mobile layout are `INCONCLUSIVE`; no local server/browser session was authorized or required for this source-only task.

## Rollback Reference

UI-only fixes should revert to the last reviewed frontend commit. They must not trigger backend, worker, Azure, provider, or production mutations during validation; use mocked/local API responses for interaction tests.

## Quality Gates

The shared CP-010 gates are recorded in `docs/evidence/CP-010-security.md`. Full pytest, Ruff check, Ruff format check, compileall, and `git diff --check` passed in this worktree.

## Remaining Risks

- Browser-only DOM data-flow behavior needs CP-005 dynamic testing.
- Actual role visibility needs screenshots for owner, writer, reader, and unauthenticated sessions.
- API authorization remains the security boundary; UI hiding alone must never be accepted as authorization evidence.
