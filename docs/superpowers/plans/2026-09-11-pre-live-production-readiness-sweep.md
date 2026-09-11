# CashPilot Pre-Live Production Readiness Sweep

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to execute this plan task-by-task.

**Goal:** Establish an evidence-backed production gate for CashPilot before live testing, covering code, security, operations, provider policy, proxy networking, UI/UX, and release integrity.

**Architecture:** Start read-only. Inventory the repository, deployed surfaces, schedules, provider adapters, proxy leases, workers, and dashboards. Exercise the authenticated UI through Chrome profile 40. Fix only reproducible defects with focused regression tests, then rerun the full verification matrix. Live node mutation is the final gated phase, not part of the audit.

**Tech Stack:** FastAPI/Python, SQLite/aiosqlite, HTML/JS/CSS, Docker, pytest, Ruff, Bandit, pip-audit, Playwright/CDP, GitHub Actions, GHCR.

## Global Constraints

- Do not delete, recreate, rotate, release, or redeploy live nodes during audit.
- Preserve user-created iOS/Ubuntu schedulers and all `.tmp-*` evidence artifacts.
- Never print or store raw tokens, cookies, passwords, SSH keys, or proxy credentials in evidence.
- Unknown telemetry is `unverified`, never `pass`.
- Destructive UI actions require two confirmations and are not clicked during audit.
- Do not claim zero-leak without packet capture plus reboot-persistence evidence.
- Keep provider-specific behavior behind adapters; do not mutate unsupported providers through generic policy code.
- Do not clean, migrate, or reuse the two legacy test VPSs as a release gate; preserve their NKN/EarnApp data.
- Keep Azure, CashPilot, GHCR, provider, proxy, and browser secrets outside Git and evidence output.
- The clean Azure test topology is exactly two Ubuntu 24.04 x64 `Standard_D8s_v4` VMs with 10 public IPv4 addresses each.

## Task 1: Baseline and change control

**Files:** `docs/evidence/pre-live-baseline-2026-09-11.md`, release manifests, deployment manifests.

- Record branch, commit, dirty files, open PRs, release versions, image tags/digests, worker versions, scheduled jobs, active services, and provider inventory.
- Classify every dirty file as expected audit change, user artifact, or unexplained change.
- Snapshot database counts for workers, nodes, proxies, leases, accounts, payments, collectors, and alerts without mutation.
- Stop the gate if unexplained source changes or credential exposure appear.

## Task 2: Security and dependency audit

**Files:** `app/main.py`, `app/database.py`, `app/orchestrator.py`, `app/worker_api.py`, collectors, frontend, Docker/CI manifests.

- Trace authentication, authorization, CSRF/session handling, SQL, subprocess/SSH, token storage, HTML escaping, CORS/CSP, rate limits, and secret redaction.
- Run full pytest, Ruff, Bandit, pip-audit, route enumeration, security-header checks, and image/config scans.
- Classify findings as confirmed, false positive with evidence, or unverified; fix only confirmed defects.
- Add a focused regression test before each code fix.

## Task 3: Policy, scheduler, and data-flow audit

**Files:** provider catalog/adapters, lifecycle scheduler, proxy lease/release/rotation code, account/payment pools, collectors, heartbeat/reconciliation routes.

- Map every state transition: create, link, heartbeat, restart, recreate, rotate, release, recovery hold, quarantine, account suspension, and deletion.
- Verify EarnApp policy: hourly earnings-cycle check; offline => restart; banned/invalid node => recreate/link; usage flatline => restart; token expiry => alert/retry/import; account suspended => release proxy; proxy rotation => delete old remote node and create a new node.
- Verify sticky egress ownership, account deletion semantics, PayPal assignment/quarantine, collector cadence, and replacement tickets.
- Compare database rows, worker heartbeat inventory, Docker inventory, proxy egress, and dashboard counters; report drift and duplicate schedules.
- Check that generic lifecycle helpers are not advertised as active for providers lacking adapters.

## Task 4: Proxy, DNS, and runtime leak audit

**Files:** provider runtime contracts, Redsocks/iptables/sing-box/DoH configs, worker network setup, `docs/evidence/provider-proxy-leak-audit.md`.

- Build a matrix per active provider for direct IPv4, IPv6, DNS, DoH bypass, UDP/WebRTC, process bypass, proxy egress, and reboot persistence.
- Capture packets in diagnostic mode, correlate observed egress with lease ownership, and test DNS failure behavior.
- Verify Wipter post-DNS behavior first, then test NKN, Earn.fm, IPRoyal, Mysterium, PacketStream, Proxies-SX, Proxybase, ProxyRack, Repocket, Spide, Traffmonetizer, UpRock, URnetwork, and other active runtimes.
- Mark untested providers `unverified`; do not infer behavior from EarnApp.

## Task 5: Chrome profile 40 UI/UX sweep

**Files:** `docs/evidence/ui-ux-browser-sweep-2026-09-11.md`, screenshots/evidence directory, templates/static assets only when defects are reproducible.

- Connect to authenticated Chrome profile 40 through CDP without killing or restarting the user’s Chrome session.
- Visit every navigation surface: Dashboard, Setup Wizard, Catalog, Fleet, Proxy Providers, Proxy Pool, EarnApp accounts, collectors, payments/PayPal, payouts, MYST Wallet, NKN Wallet, Settings, reconciliation, and provider runtime pages.
- Capture full-page screenshots plus DOM/text evidence for each page and each major section.
- Click every non-destructive button; test valid, invalid, empty, duplicate, boundary, loading, timeout, retry, pagination, filtering, and permission-denied inputs.
- Verify labels, grouping, status semantics, stale-data indicators, empty/error states, confirmation dialogs, keyboard focus, contrast, touch target size, responsive layout, and absence of horizontal overflow.
- Fix only reproducible defects; add `tests/test_ui_audit_regressions.py` for every fix.

## Task 6: Cross-system consistency audit

**Files:** capability map, policy/data-flow evidence, dashboard routes, reconciliation reports.

- Reconcile displayed counters against source-of-truth tables and worker reports.
- Validate terminology: `eligible`, `leaseable`, `leased`, `sticky-owned`, `duplicate-egress`, `offline`, `banned`, `suspended`, `quarantined`, and `unverified`.
- Check pagination and aggregation do not hide rows or double-count egress/account ownership.
- Verify scheduler idempotency, retry backoff, one-provider/one-node sequencing, and restart persistence.

## Task 7: Verification and release gate

**Files:** evidence reports, PR branch, release manifests.

- Run targeted tests, full pytest, Ruff, Bandit, pip-audit, build, route/security smoke, and image manifest checks.
- Wait for required CI checks; do not merge while pending/failing.
- Verify published UI/worker image digests independently and confirm deployed content matches the release.
- Produce a findings report with statuses only: `fixed`, `verified`, `unverified`, `blocked`, `requires user decision`.
- Propose live canary only when all required gates pass; otherwise list exact blockers and evidence.

## Task 8: Clean Azure live-test environment

**Files:** `D:\1. WORK_true\CashPilot\azure_create_vps_cli.txt`, local redacted Azure inventory, `docs/evidence/azure-live-test-2026-09-11.md`.

- Pin subscription `0e4b9f20-f92f-4883-a598-3251b0016d65`; preflight `Standard_D8s_v4`, DSv4/regional vCPU quota, Ubuntu 24.04 x64 Gen2 image, and 10 Standard static IPv4 addresses in both `eastasia` and `japaneast`.
- Create one 512 GB Premium SSD P20 OS disk per VM, one regional VNet/subnet/NSG/NIC, and 10 one-to-one public/private IPv4 mappings per NIC.
- Require an explicit switch for full Internet TCP/UDP exposure at both Azure NSG and Ubuntu UFW layers; record the accepted attack surface in evidence.
- Keep the administrator password and embedded CashPilot API key out of Git, console output, and inventory artifacts.
- East Asia verifies the canonical bootstrap by manual execution of `client command setup script.txt`.
- Japan East verifies cloud-init bootstrap plus CashPilot server auto-deploy without manual provider installation.
- Verify 20 unique public IPv4 slots, route readiness, Docker/runtime disk use, `LimitNOFILE`, worker enrollment, heartbeat, reboot persistence, and no direct-IP fallback.

## Task 9: Provider input completion

**Files:** encrypted runtime settings only, `docs/evidence/provider-input-readiness-2026-09-11.md`.

- Connect to the already authenticated provider sessions in Chrome profile 40 without restarting Chrome.
- Inventory collector/runtime/account/payment inputs; import only values required by current provider adapters.
- Record missing values by provider and field name without printing secret values.
- Do not begin destructive/full live deployment until every required input is either verified or explicitly waived.

## Task 10: Full live failure matrix

**Files:** `docs/evidence/full-live-matrix-2026-09-11.md`, packet captures with credentials redacted.

- Deploy providers sequentially; deploy nodes sequentially inside each provider so one failure cannot block the queue.
- Verify node count follows 10 public IPv4 slots for direct/proxy provider modes.
- Exercise lease, release, sticky egress ownership, rotation, account/token expiry, PayPal assignment, collector cadence, heartbeat, reconciliation, retry/backoff, and auto-deploy.
- Stop a test VPS for more than one hour; verify recovery hold, stale-worker behavior, proxy/account ownership, re-enrollment, and restart persistence.
- Capture IPv4, IPv6, DNS/DoH, UDP/WebRTC, and direct-IP bypass evidence per provider; mark missing proof `unverified`.
- Rerun the UI/UX, security, consistency, test, CI, image-digest, and deployed-version gates after live fixes.
- Produce the final production-readiness report, remaining risk list, cost/security optimizations, and private-repository production recommendation.

## Required outputs

- Baseline, security, policy/data-flow, proxy-leak, UI/UX, and final findings reports under `docs/evidence/`.
- Updated capability map covering providers, runtimes, workers, leases, accounts, collectors, payments, heartbeat, recovery, reconciliation, security, UI, CI/CD, and external dependencies.
- No live mutation during audit.

## Current known blockers

- Chrome profile 40 CDP/connector is unavailable in the current session; authenticated browser evidence cannot be claimed until it is exposed safely.
- Fleet-wide packet/reboot proof is incomplete; the clean Azure matrix in Tasks 8-10 replaces the legacy VPS cleanup blocker.
- PayPal live behavior, non-EarnApp account adapters, and live token auto-import remain unverified.
- Local audit changes are not yet committed/pushed/released.
