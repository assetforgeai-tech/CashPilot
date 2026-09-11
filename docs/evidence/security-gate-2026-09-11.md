# Security gate — 2026-09-11

- Bandit audit over `app`: `91` triaged results, `0` HIGH severity.
- `pip-audit -r requirements.txt --progress-spinner off` completed successfully:
  `No known vulnerabilities found`.
- The previously confirmed EarnApp qualification weakness (TLS certificate and
  hostname verification disabled) is fixed in the current mainline and covered
  by regression tests requiring `CERT_REQUIRED` and hostname verification.
- No additional confirmed secret disclosure, XSS, CSRF, redirect, or public
  endpoint authorization issue was found in the current source review.

No dependency vulnerability was reported by the completed scan. Other unknown
or incomplete runtime evidence remains `unverified`; it is not evidence of
production safety.
