# Security gate — 2026-09-11

- Bandit audit over `app`: `91` triaged results, `0` HIGH severity.
- `pip-audit` was attempted against `requirements.txt`; the local resolver did
  not return a completion result in the bounded run, so dependency status stays
  `unverified` here rather than being promoted to pass.
- The previously confirmed EarnApp qualification weakness (TLS certificate and
  hostname verification disabled) is fixed in the current mainline and covered
  by regression tests requiring `CERT_REQUIRED` and hostname verification.
- No additional confirmed secret disclosure, XSS, CSRF, redirect, or public
  endpoint authorization issue was found in the current source review.

Unknown or incomplete scanner output remains `unverified`; it is not evidence
of production safety.
