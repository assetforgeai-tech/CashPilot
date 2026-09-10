# EarnApp Token Refresh Audit

- Import accepts only the allowlisted OAuth/XSRF cookies.
- JWT `exp` is decoded when the refresh token is a JWT; opaque refresh tokens remain `expiry_unknown`.
- Browser extension import is challenge-bound to the declared Chrome profile.
- Dashboard exposes `token_expiry_source`, `token_expires_at`, `cookie_expires_at`, and warning bands.
- Collection classifies authentication rejection without logging token or cookie values.
- Automatic browser login is extension-side and operator-gated per profile. It polls only the server refresh flag, then uses the already-authenticated Google/Apple browser session; CAPTCHA, MFA, OTP, missing controls, or account mismatch stop with `operator_required`.
- Token upload is event-driven: cookie changes debounce a sync; there is no periodic secret upload loop.
