# v1.53.17 Traffmonetizer rollout (2026-09-16)

Release `v1.53.17` contains the collector cooldown fix. The
`Retry-After` deadline is now module-level, so scheduled runs that construct a
new collector instance still honor the provider cooldown within the running
server process.

## Verification

- Regression test added for a second collector instance during the same
  cooldown; focused collector suite: `84 passed`.
- Release workflow completed successfully: tests, lint, CodeQL, image builds,
  GHCR tag resolution/version verification, and release publication.
- Server UI upgraded to `ghcr.io/assetforgeai-tech/cashpilot:1.53.17`,
  `running|healthy`; worker preserved.
- Both Azure workers upgraded to
  `ghcr.io/assetforgeai-tech/cashpilot-worker:1.53.17`, `running|healthy`,
  with 285/285 managed containers running and provider state preserved.
- Bounded post-rollout collector calls still report Traffmonetizer
  `rate_limited`; this is expected while the upstream cooldown remains active.
  Repocket still reports missing `REPOCKET_FIREBASE_KEY`.
