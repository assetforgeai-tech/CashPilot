# Active CashPilot Context

- Canonical Git directory: D:\1. WORK_true\CashPilot\repo
- Active integration worktree: D:\1. WORK_true\CashPilot\repo-consolidation-20260921
- Migration source: D:\1. WORK_true\CashPilot\repo-spide-release-20260916
- Allowed live worker: 118904
- Forbidden workers/environments: test-sing, test-us, sing, eapp
- Production mutation: prohibited during consolidation
- Source precedence: integration worktree > reviewed migration artifact > historical worktree > chat history
- Current phase: 8
- Phase 7 gate: PASS (controlled disposable scope)
- Phase 8 audit: COMPLETE; see `docs/evidence/consolidation-final-audit-2026-09-21.md`
- Next action: obtain explicit exact cutover/destructive-action approval; do not merge, push, delete, remove, rename, or mutate production before approval
- Verification command: pytest -q && ruff check app tests && python -m compileall -q app tests && git diff --check

## Retained NKN snapshot evidence

- ChainDB snapshot handling remains documented in `docs/guides/nkn.md`; only the
  private `ChainDB/` payload is eligible, while wallet, password, config and
  node identity remain outside the archive.
- The retained behavior matrix records the protected NKN release as `v1.6.2`
  at commit `bb52dea`, with verified worker digest
  `sha256:4909468c68b1d5c7b186b0596e966f3f28db4325588725e2162ee0f09db90f03`.
- The protected status is `PROTECTED_DONE`; the publisher VPS host-helper
  persistence contract is `PERSIST_FINISHED`; the publisher timer is `active (waiting)`.
  This is a historical/protected reference only; consolidation performs no live mutation.

## Current source policy (unreleased, 2026-08-29)

The retained provider source policy is historical reference material during this
consolidation. **Historical v1.14.1 status:** `COMPLIANCE_BLOCKED` / `RUNTIME_DISABLED`.
Current provider truth remains defined by the reviewed catalog and runtime policy,
not by this historical checkpoint.
