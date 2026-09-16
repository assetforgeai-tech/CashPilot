# Production gate status (2026-09-16)

## Proven

- Spide runtime/collector boundary: node containers run only the official CLI;
  registration and dashboard collection remain server-side.
- R2 artifact parity: pinned archive and executable hashes match live samples.
- Spide live health: sampled nodes on both Azure workers emit recurring
  `Status: OK`.
- Release parity: UI and workers run `1.53.16`; deployed image tags, baked
  version, digest, and platform agree.
- Reboot persistence: both workers rebooted sequentially and returned healthy
  on `1.53.16`; 285/285 managed containers remained running; worker data,
  identity, key, and provider inventory were preserved.
- CI: focused Spide tests and PR checks passed; PRs #437, #438, #439, #440,
  and #441 were merged.

## Still open

- Provider HTTP `500`: no redacted request/response trace has been captured.
- Network security: current read-only probes are inconclusive for packet-level
  direct fallback, UDP, DoH, and DoT leakage.
- Provider-wide earnings/collector proof: Repocket credential setup and
  Traffmonetizer recovery remain unresolved in the current authority snapshot.
- Full requirement-by-requirement production report and residual-gap review.

The goal remains active. Open gates are not converted to success by indirect
signals or by the passing CI suite.
