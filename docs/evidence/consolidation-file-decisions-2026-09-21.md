# Consolidation File Decisions — 2026-09-21

Classification compares the migration source with origin/main. It does not import, move, delete, stage, or commit any source file.

## Coverage

- Changed tracked paths: 61
- Untracked paths: 144
- Total classified paths: 205
- ARCHIVE_EVIDENCE: 72
- ARCHIVE_SCRATCH: 71
- KEEP_DOC_CURRENT: 2
- KEEP_TEST: 32
- REVIEW_REQUIRED: 28
- REVIEW_REQUIRED paths without a slice: 0

## Decision rules

- Production code, runtime definitions, bootstrap scripts, and durable tools remain REVIEW_REQUIRED until slice review.
- Tests are KEEP_TEST candidates but remain coupled to their owning slice; classification is not acceptance.
- Current guide/plan material is KEEP_DOC_CURRENT; historical plans and live evidence are ARCHIVE_EVIDENCE.
- .tmp-*, extracted images, tarballs, overrides, and one-off patch/probe helpers are ARCHIVE_SCRATCH.
- No path is marked SECRET_EXCLUDE solely from a filename. Phase 1 secret/path manifests remain the credential boundary; raw values are never copied into review artifacts.

## Duplicate evidence check

- SHA256 E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855: docs/evidence/live-proxy-egress-audit-2026-09-18-v3.json, docs/evidence/live-proxy-egress-audit-2026-09-18.json, docs/evidence/live-proxy-egress-audit-2026-09-21.json, docs/evidence/ui-ux-browser-sweep-2026-09-12/catalog.txt, docs/evidence/ui-ux-browser-sweep-2026-09-12/dashboard.txt, docs/evidence/ui-ux-browser-sweep-2026-09-12/fleet.txt, docs/evidence/ui-ux-browser-sweep-2026-09-12/myst-wallet.txt, docs/evidence/ui-ux-browser-sweep-2026-09-12/nkn-wallet.txt, docs/evidence/ui-ux-browser-sweep-2026-09-12/payouts.txt, docs/evidence/ui-ux-browser-sweep-2026-09-12/proxy-pool.txt, docs/evidence/ui-ux-browser-sweep-2026-09-12/proxy-providers.txt, docs/evidence/ui-ux-browser-sweep-2026-09-12/settings.txt, docs/evidence/ui-ux-browser-sweep-2026-09-12/setup.txt

Byte identity alone does not authorize deletion. Duplicate evidence remains frozen until Phase 8 approval.

## Gate

The CSV is the authoritative one-row-per-path classification. Every REVIEW_REQUIRED path has a review slice. No migration content was imported into the integration worktree.
