# Consolidation Security Review — 2026-09-21

Scope: migration source `repo-spide-release-20260916` versus `origin/main`.
Review was read-only. No production mutation, source import, or auto-fix occurred.

## Confirmed findings

No critical, high, or medium vulnerability is confirmed from the independent
auth/API, frontend, and worker/runtime passes.

The worker/runtime pass examined the generic runtime-asset endpoint around
`app/main.py:8780-8788`. It found a conditional concern: generic assets are
provider-scoped while the authorization check is worker assignment scoped. The
current service model declares several of these assets as provider-wide, so the
code does not prove an exploitable cross-tenant disclosure under the current
trust model. Record as hardening/review-required, not a confirmed vulnerability.

## Checks

- Frontend/security-focused tests reported by the independent pass: 180 passed.
- Full suite reported by the independent pass: 3446 passed, 7 skipped.
- No confirmed Docker escape, shell/path injection, auth bypass, CAS proxy-reuse
  race, or frontend XSS was found.
- Migration-source test subset executed read-only: `1246 passed`.
- Packet-level DNS/DoH/IPv6/UDP/direct-fallback proof remains deployment evidence,
  not a source-only security conclusion.

## Hardening notes (not findings)

- Bind non-EarnApp runtime assets to an explicit instance or declared asset grant
  if provider credentials become account/instance-specific.
- Centrally validate external URL schemes in catalog/dashboard/referral links.
- Replace trusted `innerHTML` uses with DOM APIs where practical.

## Gate status

Security review is complete for the available source. Independent OCR remains
blocked because no configured LLM endpoint/token/model is present on this host;
no findings were fabricated to bypass that gate.
