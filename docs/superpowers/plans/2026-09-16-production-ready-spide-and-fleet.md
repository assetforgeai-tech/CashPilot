# Production Ready Spide And Fleet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Verify Spide runtime/collector boundaries and remaining production gates without running dashboard collectors inside provider nodes.

**Architecture:** Provider containers execute only declared runtime binaries. Registration and collection remain server-side adapters. Artifacts are checksum-pinned; live changes require canary evidence.

**Tech Stack:** Python, FastAPI, Docker Compose, YAML catalogs, pytest, GitHub Actions, Azure workers.

## Global Constraints

- Spide uses the R2 ZIP and SHA-256 `04F31522CBDB03B3D11E5293A3A18C6E910AED11B6D8B431B560BC7CB4ED08E5`.
- Spide collector is dashboard/manual-only and never executes in a node container.
- Preserve provider identities and unrelated worktree changes.

### Task 1: Lock Spide runtime boundary

- [x] Pin artifact and checksum.
- [x] Set empty collector source and dashboard-only kind.
- [x] Document server-side device registration.
- [x] Run focused tests.

### Task 2: Verify live artifact and registration evidence

- [x] Record archive contents, checksum, catalog command, and registration boundary.
- [ ] Capture current worker logs and dashboard registration response with secrets redacted.
- [ ] Classify provider-reported version mismatch using direct node evidence.

### Task 3: Production gate sweep

- [x] Run full Python tests and catalog validation.
- [ ] Verify registry image/tag parity.
- [x] Verify Azure heartbeats, inventory, provider dashboard traffic, and no unintended recreation.
- [ ] Run network/security and reboot lifecycle checks.

### Task 4: Release verified changes

- [x] Commit isolated documentation/evidence changes.
- [x] Create PR, pass checks, merge, deploy matching image.
- [ ] Recheck Spide runtime after rollout.
- [x] Recheck Spide runtime after rollout.

### Task 5: Closeout

- [ ] Produce requirement-by-requirement production report.
- [ ] List residual gaps and evidence.
- [ ] Mark goal complete only after every gate is proven.
