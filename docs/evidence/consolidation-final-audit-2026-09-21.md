# CashPilot Consolidation — Phase 8 Final Audit

Date: 2026-09-21
Scope: audit only. No merge, push, branch deletion, worktree removal, folder
rename, or folder deletion was performed.

## 1. State and authority

| Item | Current state | Evidence |
|---|---|---|
| Canonical Git directory | `D:\1. WORK_true\CashPilot\repo`, branch `fix/nkn-chaindb-python310`, HEAD `cc05eebcfd53` | `git worktree list`, `git status` |
| Integration worktree | `D:\1. WORK_true\CashPilot\repo-consolidation-20260921`, branch `consolidation/cashpilot-20260921`, HEAD `cf8229c31e39` | `docs/architecture/source-of-truth.md` |
| Migration source | `D:\1. WORK_true\CashPilot\repo-spide-release-20260916`, branch `fix/spide-production-closeout-20260916`, HEAD `44c33d3a4db0` | worktree inventory |
| Integration base | `origin/main` at `cf8229c31e39`; ahead/behind `0/0` | `git rev-list --left-right --count origin/main...HEAD` |
| Integration commit state | No Phase 6/7 commit exists; all retained changes remain unstaged/uncommitted | `git log`, `git status --short` |
| Canonical dirty state | 9 pre-existing entries, including `app/provider_automation.py`, its test, and scratch/archive surfaces | `git status --short` |
| Production mutation | None performed by this consolidation | Phase 7 evidence and live authority sweeps |

## 2. Requirement-by-requirement audit

| Requirement | Result | Proof / limitation |
|---|---|---|
| Preserve canonical repository identity | PASS | Source-of-truth map; integration was a separate worktree from `origin/main`. |
| Preserve migration source and dirty state | PASS | Migration worktree remains registered and untouched by cutover. Canonical dirty entries remain present. |
| Curated integration, no blind branch merge | PASS | Phase 6 evidence: slices 1–9 imported selectively; no branch-wide merge. |
| DB authority, CAS, leases, sticky provider ownership | PASS (static/live scoped) | Runtime authority map; DB/CAS tests; disposable staged replacement and cleanup converged. Production reconciliation not claimed. |
| EarnApp account/token/link/lifecycle/recovery | PASS (disposable scope) | Account/lifecycle test suites; serialized operation tests; Phase 7 disposable API path. Provider dashboard earnings are outside this consolidation gate. |
| Runtime renderer and catalog contracts | PASS | Focused runtime/provider tests; image smoke/import checks; immutable image digests recorded in Phase 7 evidence. |
| DNS/DoH, IPv6, UDP, direct-fallback fail-closed | PASS (disposable scope) | Fresh packet capture and firewall counters for `phase7c`; direct HTTPS failed; IPv6 chain DROP; proxy egress matched. No claim for untested production nodes. |
| Watchdog / repeated-health / staged replacement | PASS (disposable scope) | Fault injection returned `3/3` unhealthy, `direct_fallback_blocked=true`, `rotation_requested=true`; generation/device changed after replacement. |
| Worker restart persistence | PASS (worker 118904 scope) | Worker restarted twice; healthy image returned; managed inventory stable hash/count unchanged; disposable egress remained healthy. |
| Retry / rollback behavior | PASS (disposable scope) | Staged recovery tests and fault-injection path; old runtime preserved until replacement verification. |
| Cleanup convergence | PASS | Normal API cleanup returned HTTP 200; final authority sweep: 183 containers, no disposable residue, no `proxy-011` active lease. |
| Collectors, payments, account pools | PASS (code/test scope) | Collector/payment/account-pool tests and review slices. External payment reconciliation is not re-proven by Phase 8. |
| Dashboard/API/UI wiring | PASS (static/test scope) | UI/API focused tests and host review. No new visual browser sweep was performed in Phase 8. |
| Worker authentication and runtime asset scope | PASS with hardening note | Security review found no confirmed Critical/High/Medium issue; provider-wide asset scope should be narrowed if assets become account-specific. |
| Azure/GHCR/bootstrap equivalence | PARTIAL | Image/build smoke and startup tests pass; production cutover equivalence remains unverified and requires explicit deployment approval. |
| Secret/artifact boundary | PASS for integration artifacts | Phase 7 secret-path scan; no credentials, DBs, cookies, runtime volumes, or raw provider responses imported. |
| OCR review | PARTIAL / provider unavailable | Deterministic OCR delegate preview/rules completed; provider-backed OCR could not run because no approved LLM endpoint/token/model was configured. Host review covered all nine slices. |
| Production/provider dashboard earning reconciliation | OUT OF SCOPE | Plan explicitly separates transport evidence from provider earnings; no production earning node was mutated. |

## 3. Commit list and diff summary

### Integration branch

- HEAD: `cf8229c31e39d66e855b83ab671253b9429bdd71`
- HEAD subject: `docs: record v1.53.17 collector rollout`
- Commits ahead of `origin/main`: `0`
- Phase 6/7 changes: uncommitted working-tree changes, intentionally preserved
  for explicit cutover review.
- Tracked diff: 44 files, approximately `4887` insertions and `2278` deletions.
- Untracked integration paths: 36.
- Main changed areas: DB/CAS (`app/database.py`), EarnApp lifecycle/runtime,
  orchestrator/worker API, proxy renderer/sidecar/DNS policy, provider topology,
  tests, evidence, architecture maps, and Azure startup tooling.

### Canonical and migration branches

- Canonical `repo`: HEAD `cc05eebcfd537a0ee16f19093db8a4776e86ae98`; dirty state is
  not part of the integration diff and must be preserved before any cutover.
- Migration source: HEAD `44c33d3a4db00f5f3a6dc7f50eaa439024b02a94`; 161 dirty
  entries including temporary archives and evidence. It remains frozen.
- No merge, commit, push, rebase, reset, or checkout was performed in this audit.

## 4. Test, security, OCR, and live evidence

- Final local verification: `3348 passed, 7 skipped`.
- Ruff: `All checks passed!`.
- `python -m compileall -q app tests`: passed.
- `git diff --check`: passed, with only Windows LF/CRLF warnings.
- Security review: no confirmed Critical/High/Medium vulnerability; conditional
  runtime-asset scope hardening recorded in
  `docs/evidence/consolidation-security-review-2026-09-21.md`.
- OCR: nine deterministic slices selected and reviewed; provider-backed OCR is
  unavailable without configured endpoint/model/token.
- Live: only disposable canaries on Azure worker `118904`; worker `118903` was
  offline and untouched. No `test-sing`, `test-us`, `sing`, `eapp`, or production
  earning node was used.
- Immutable images: UI and worker digests, smoke/import checks, and secret scan
  are recorded in `docs/evidence/consolidation-phase-7-2026-09-21.md`.

## 5. Worktree and branch retirement candidates

These are **candidates only**. None is approved for removal. Exact path/branch
must be rechecked for unique content immediately before any future destructive
operation.

| Candidate path | Branch/state | Audit disposition |
|---|---|---|
| `D:\1. WORK_true\CashPilot\archive\20260921\ocr\slice-1-worktree` through `slice-9-worktree` | detached at `cf8229c31e39`, overlay-dirty | Retire only after preserving review overlays/manifests. |
| `D:\1. WORK_true\CashPilot\codex-scratch\earnapp-20260905-runtime` | `fix/earnapp-doh-proxy`, clean | Historical candidate; verify unique commits/evidence first. |
| `D:\1. WORK_true\CashPilot\codex-scratch\earnapp-lease-heartbeat-audit` | `fix/earnapp-lease-heartbeat-dashboard`, clean | Historical candidate; verify unique commits/evidence first. |
| `D:\1. WORK_true\CashPilot\codex-scratch\earnapp-platform-registry` | `fix/proxy-ipapi-current-schema`, clean | Historical candidate; verify unique commits/evidence first. |
| `D:\1. WORK_true\CashPilot\repo-earnapp-legacy-hotfix` | `feat/earnapp-standardization-main`, clean | Historical candidate; do not remove before branch/content audit. |
| `D:\1. WORK_true\CashPilot\repo-earnapp-legacy-migration` | `fix/earnapp-legacy-schema-migration`, clean | Historical candidate; do not remove before branch/content audit. |
| `D:\1. WORK_true\CashPilot\repo-earnapp-migration-safety` | `fix/earnapp-migration-safety`, clean | Historical candidate; do not remove before branch/content audit. |
| `D:\1. WORK_true\CashPilot\repo-earnapp-proxy-pool` | `fix/proxy-import-enrichment`, clean | Historical candidate; do not remove before branch/content audit. |
| `D:\1. WORK_true\CashPilot\repo-nkn-ack-count` | `fix/nkn-ack-count-20260916`, clean | Historical candidate; do not remove before branch/content audit. |
| `D:\1. WORK_true\CashPilot\repo-nkn-v163-docs` | `docs/nkn-v163-live-closeout`, clean | Historical candidate; retain evidence until canonical acceptance. |
| `D:\1. WORK_true\CashPilot\repo-prod-rollout-20260916` | `docs/production-rollout-20260916`, clean | Historical candidate; retain rollout references. |
| `D:\1. WORK_true\CashPilot\repo-proxy-lease-safety` | `feat/earnapp-account-recovery`, clean | Historical candidate; verify unique recovery work. |
| `D:\1. WORK_true\CashPilot\repo-release-427` | `release/spide-fleet-20260916`, clean | Historical release candidate; retain until release decision. |
| `D:\1. WORK_true\CashPilot\repo-spide-evidence-20260916` | `evidence/spide-azure-runtime-20260916`, clean | Evidence candidate; archive only after hashes are preserved. |
| `D:\1. WORK_true\CashPilot\repo-spide-prod` | `fix/spide-runtime-boundary-20260916`, clean | Historical candidate; verify unique runtime boundary changes. |

The following are **not retirement candidates now**: canonical `repo`, integration
worktree, migration source, any dirty worktree, temporary PR worktrees, and any
worktree whose unique commits/content have not been compared against the Phase 1
manifests.

## 6. Cutover decision requested

Phase 8 audit is complete, but cutover is not authorized. To proceed, approve a
separate exact-action list covering:

1. Which branch receives the integration changes.
2. Whether the 44 tracked changes and 36 untracked retained artifacts are to be
   committed, and the intended commit boundary.
3. How the 9 dirty canonical entries in `D:\1. WORK_true\CashPilot\repo` are to
   be archived or committed before canonical branch change.
4. Exact worktree paths and branches approved for removal; all others remain.
5. Whether remote branch deletion is approved separately.
6. Whether production rollout is approved after merge/push (not implied by this
   audit).

Until those exact actions are approved, all branches, worktrees, folders, dirty
state, and remote refs remain unchanged.
