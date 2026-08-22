# Proxy Worker ACK Rotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use test-driven-development to implement each task with a failing test first.

**Goal:** Make proxy rotation safe by requiring a worker-local verification/ACK before CashPilot swaps an active proxy lease.

**Architecture:** The server remains the only proxy-pool and lease authority. The worker applies the server-provided binding, performs a bounded local probe from the VPS, and returns a redacted ACK containing the binding version and observed exit IP. The first implementation keeps the existing worker-level assignment schema and provider behavior unchanged; topology-slot migration is a separate follow-up.

**Tech Stack:** FastAPI, Pydantic, httpx, Docker SDK, SQLite/aiosqlite, pytest.

## Global Constraints

- Do not change provider catalog/runtime contracts or direct-only providers.
- Do not access or modify VPS, containers, volumes, databases, credentials, proxy leases, or wallet leases.
- Never return proxy username/password or raw proxy URL in ACKs, logs, or API responses.
- A failed worker ACK must leave the old database assignment intact and must not release the old proxy.
- Preserve existing endpoint compatibility and all current tests.

### Task 1: Define one worker apply-and-verify contract

**Files:**
- Modify: `app/worker_api.py`
- Test: `tests/test_proxy_egress.py`

- [x] Add a red test for one apply endpoint that returns `ok`, `binding_version`, `observed_exit_ip`, and redacted failure details without secrets.
- [x] Add a red test that invalid/missing binding version is rejected.
- [x] Implement a small Pydantic request model and `/api/egress/bindings/apply` endpoint using the existing worker-local proxy probe helper.
- [x] Keep the worker lease-blind: it applies only the exact proxy and instances supplied by the server and never selects from the pool.
- [x] Run the focused tests and then the existing proxy egress tests.

### Task 2: Make sidecars persist and acknowledge an effective binding

**Files:**
- Modify: `app/orchestrator.py`, `app/worker_api.py`
- Test: `tests/test_proxy_egress.py`, `tests/test_proxy_sidecar_runtime.py`

- [x] Add a red test proving `/api/egress/bindings/apply` requires a non-empty `binding_version`.
- [x] Add a red test proving the response contains only redacted binding metadata.
- [x] Give newly created sidecars a persistent config volume whose restart path does not overwrite a rotated configuration.
- [x] Implement atomic sidecar config replacement, restart only the named sidecars, verify their process/config hash, and return the binding version.
- [x] Refuse legacy sidecars without the persistent config mount instead of claiming a rotation succeeded.

### Task 3: Add server-side lease swap with worker ACK

**Files:**
- Modify: `app/database.py`, `app/routers/proxies.py`
- Test: `tests/test_proxy_routes.py`

- [x] Add a red test that a dead assigned proxy is not replaced in the database when worker apply/verify fails.
- [x] Add a red test that a successful apply plus matching ACK swaps the assignment and only then applies the new binding.
- [x] Implement a unique binding token plus monotonic assignment generation for each rotation attempt.
- [x] Add a helper that applies a candidate to the worker, calls local verification, and commits the assignment only after matching ACK.
- [x] Keep the previous sidecar config until DB CAS succeeds; confirm it on commit or roll it back on CAS failure.
- [x] Keep old assignment on every pre-commit exception and do not release/quarantine it from this path.
- [x] Reject a candidate claimed by another worker inside the same `BEGIN IMMEDIATE` CAS transaction.
- [x] Serialize proxy assignment transactions on the server and fail closed on mixed per-instance proxy rows.
- [x] Treat post-CAS confirm failure as cleanup-pending and never roll the committed DB row back blindly.
- [x] Attempt token-checked runtime rollback when the worker apply response is lost or returns a server-side transport error.

### Task 4: Wire periodic recheck to the safe rotation helper

**Files:**
- Modify: `app/routers/proxies.py`
- Test: `tests/test_proxy_routes.py`

- [x] Add a red test covering an assigned dead endpoint and successful worker ACK.
- [x] Replace direct `set assignment -> apply` rotation with the safe helper.
- [x] Preserve existing provider-specific mask behavior for IPRoyal/Pawns and avoid global masks.
- [x] Route manual proxy assignment/lease through ACK rotation when active proxy instances exist.
- [x] Run all proxy/deploy regression tests.

### Task 5: Document the contract and verify the branch

**Files:**
- Modify: `docs/configuration.md`, `docs/research/repo-github-understanding.md`
- Test: existing documentation contract tests

- [x] Document server authority, worker-local verification, ACK semantics, failure behavior, and current worker-level limitation.
- [x] Run focused tests, the full test suite, and `git diff --check`.
- [x] Recheck that only intended files changed and that no live-operation command was run.

## Verification checkpoint (2026-08-22)

- Focused proxy/deploy/MYST regression: `111 passed in 4.57s`.
- Full suite: `1357 passed, 7 skipped in 37.78s`.
- `ruff check`, targeted `ruff format --check`, `compileall`, `uv lock --check`, deploy-baseline, and `git diff --check`: passed. The diff check emitted only LF/CRLF conversion warnings, not whitespace errors.
- Final diff review added SOCKS support to the locked worker runtime, serialized rotations per worker, required full finalize ACK instance matching, ignored failed instance tombstones, preserved manual fallback policy, and routed deploy-time dead-proxy replacement through the same ACK path.
- Changed-file review: only proxy ACK/sidecar/database/deploy-path implementation, dependency manifests, tests, and contract documentation changed; no provider catalog or provider-specific runtime contract changed.
- Operational boundary: no VPS, live container, volume, database, credential, proxy lease, wallet lease, release, or deploy operation was performed in this phase.

## Post-merge checkpoint (2026-08-22)

- CodeQL identified the request-supplied probe target as a full SSRF path. A
  regression test was added first; the worker probe endpoint now rejects custom
  target lists and uses only its built-in safe targets.
- Fix commit: `31e35b2`; local verification after the fix: `1358 passed, 7
  skipped`, `ruff check`, targeted format, compileall, lockfile and deploy
  baseline all passed.
- PR #7 passed CodeQL, Analyze, Documentation/build, Lint and Tests, then was
  squash-merged as `78e9553` with `[skip ci]`.
- No release, tag, GHCR image publication, VPS operation, container operation,
  proxy lease operation or wallet operation followed the merge. Latest published
  release remains `v1.1.1`.
- The next independent phase is a read-only release-readiness audit; topology-slot
  migration and any canary/deploy require a separate impact map and explicit
  approval.
