# Repocket credential remediation — 2026-09-12

- Removed the Firebase API key literal from `app/collectors/repocket.py`.
- Collector now requires `REPOCKET_FIREBASE_KEY` at runtime and sends it as a
  request parameter without exposing it in logs or responses.
- Contract test asserts no `AIza` literal remains in the collector source.
- Collector contract suite: `67 passed, 1 skipped`; Ruff clean.
- Deployment must inject `REPOCKET_FIREBASE_KEY` through the existing secret
  mechanism before enabling Repocket collection. Missing configuration fails
  closed with a clear error.
