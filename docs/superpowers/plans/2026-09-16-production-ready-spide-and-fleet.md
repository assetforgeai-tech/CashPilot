# Production Ready Spide And Fleet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make provider runtime/collector boundaries and the remaining production gates verifiable without running dashboard collectors inside provider nodes.

**Architecture:** Provider containers run only their declared runtime binary. Account registration and dashboard collection remain server-side adapters. Versioned artifacts use immutable checksums; live changes use canary, evidence, then rollout.

**Tech Stack:** Python, FastAPI, Docker Compose, YAML catalogs, pytest, GitHub Actions, Azure workers.

## Global Constraints

- Spide runtime uses only the authoritative R2 ZIP and pinned SHA-256 `04F31522CBDB03B3D11E5293A3A18C6E910AED11B6D8B431B560BC7CB4ED08E5`.
- Spide collector is dashboard/manual-only and must never execute in a node container.
- Preserve unrelated working-tree changes and provider identities.
- Do not bulk-redeploy stateful providers.

### Task 1: Lock Spide runtime boundary

**Files:** `services/bandwidth/spide.yml`, `app/provider_runtime.py`, `tests/test_catalog_loader.py`, `docs/guides/spide.md`

- [x] Pin R2 artifact and checksum.
- [x] Set empty collector source and dashboard-only kind.
- [x] Document server-side device registration boundary.
- [x] Run focused catalog/automation tests.

### Task 2: Verify live artifact and registration evidence

**Files:** `docs/evidence/spide-runtime-vs-raw-code-audit-2026-09-15.md`, `docs/evidence/spide-production-verification-2026-09-16.md`

- [x] Record ZIP contents, archive/executable checksums, catalog command, and registration API boundary.
- [x] Capture current worker runtime version/hash evidence and dashboard registration response without secrets.
- [x] Classify version mismatch as unobservable from the provider dashboard; verify the deployed executable instead.

### Task 3: Production gate sweep

**Files:** existing test suites and evidence only unless a failing gate identifies a code defect.

- [x] Run full Python tests and catalog validation.
- [x] Classify Repocket collector failure and remove its hard-coded Firebase key;
  server environment wiring and regression tests are in place.
- [x] Classify Traffmonetizer `429` as an upstream rate-limit condition rather
  than a runtime/container failure.
- [x] Add bounded `Retry-After` cooldown handling so scheduled collection does
  not hammer the upstream login endpoint.
- [ ] Check image/tag parity for server and worker releases.
- [ ] Verify Azure worker heartbeats, provider inventory, and no unintended recreation.
- [ ] Run network/security matrix and lifecycle smoke checks.

### Task 4: Release only verified changes

- [ ] Commit isolated Spide/docs changes only after tests pass.
- [ ] Create PR, wait for required checks, merge, and deploy the matching image.
- [ ] Recheck Spide runtime and dashboard evidence after rollout.

### Task 5: Closeout audit

- [ ] Produce requirement-by-requirement production report.
- [ ] List residual gaps with concrete evidence and next action.
- [ ] Mark the goal complete only when every required gate is proven.
