# Repocket collector secret remediation (2026-09-16)

The live server logs showed two distinct conditions: Repocket failed because
`REPOCKET_FIREBASE_KEY` was missing, while the source still contained a
hard-coded Firebase key. The key literal has been removed.

- `app/collectors/repocket.py` now reads `REPOCKET_FIREBASE_KEY` at
  authentication/refresh time and fails closed with a clear setup error when it
  is absent.
- `docker-compose.yml` and `docker-compose.fleet.yml` pass the value only to the
  CashPilot UI/server container.
- The provider node runtime still receives only its own `RP_EMAIL` and
  `RP_API_KEY`; Firebase collector credentials are not sent to provider nodes.
- Regression and collector contract tests pass: `96 passed, 1 skipped`.

The production server must be supplied a valid `REPOCKET_FIREBASE_KEY` before
Repocket collection can return data. No provider containers were redeployed by
this source-only remediation.
