# Pre-Live Full Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to execute this plan task-by-task.

**Goal:** Establish an evidence-backed pre-live baseline for CashPilot, fix confirmed defects, and document every remaining policy or operational gap before live testing.

**Architecture:** Run read-only repository/security/runtime audits first. Exercise the running UI through Chrome profile 40 with Playwright-style browser evidence, then make only scoped fixes with regression tests. Live provider mutations remain blocked until all applicable gates pass.

**Tech Stack:** Python, FastAPI, SQLite/aiosqlite, static JavaScript/CSS, Docker, pytest, Ruff, GitHub Actions, Chrome profile 40.

## Global Constraints

- Preserve accepted provider runtimes and existing provider assignments.
- Do not delete, recreate, rotate, release, or redeploy live nodes during the audit.
- Do not expose credentials, cookies, tokens, SSH keys, or raw secrets in evidence.
- Treat unknown, stale, or unavailable telemetry as `unverified`, never as pass.
- Keep user-created scheduler behavior intact unless a confirmed defect requires a scoped fix.
- Use double confirmation for destructive UI actions; do not invoke them during this audit.

### Task 1: Baseline and change-control snapshot

**Files:**
- Create: `docs/evidence/pre-live-baseline-2026-09-10.md`
- Inspect: `git status`, release manifests, deployment baseline, existing evidence

- [x] Record branch, commit, release versions, dirty files, active PRs, and known worker versions. Image digest/live worker verification remains part of rollout.
- [x] Classify dirty files as user artifacts, expected changes, or unexplained changes; no unexplained source changes found.
- [ ] Record active services, workers, provider instances, and current scheduler jobs without mutating them.
  Current state: repository baseline recorded; live worker snapshot still pending.

### Task 2: Security review

**Files:**
- Create: `docs/evidence/security-review-2026-09-10.md`
- Inspect: `app/main.py`, `app/database.py`, `app/orchestrator.py`, `app/worker_api.py`, `app/collectors/`, `app/static/js/app.js`, Docker/CI manifests

- [x] Trace the high-risk authentication, authorization, SQL, subprocess/SSH, token, and HTML/JS paths; no high-confidence exploitable issue found.
- [x] Run repository security/auth/CSP/secret regression tests and targeted static/config review. Dedicated dependency scanner remains unavailable locally.
- [x] Report only high-confidence exploitable findings; list verification items separately.
- [ ] Add regression tests before fixing any confirmed issue.

### Task 3: Backend policy and data-flow audit

**Files:**
- Inspect: provider runtime catalog, lifecycle scheduler, proxy lease/release/rotation paths, account pools, payment pools, collectors, heartbeat/reconciliation routes
- Create/update: `docs/evidence/policy-dataflow-audit-2026-09-10.md`

- [x] Map provider lifecycle states and actions: heartbeat, restart, recreate, rotate, release, recovery hold, and account suspension in `docs/evidence/policy-dataflow-audit-2026-09-11.md`.
- [ ] Verify EarnApp token expiry/retry, sticky egress ownership, PayPal assignment, collector cadence, and account deletion semantics.
- [ ] Compare DB state, heartbeat inventory, Docker inventory, proxy egress, and dashboard counters.
- [ ] Identify conflicting schedules, duplicate ownership, stale rows, false zero counters, and fail-open paths.

### Task 4: Network and runtime leak audit

**Files:**
- Update: `docs/evidence/provider-proxy-leak-audit.md`
- Inspect: provider network contracts, sidecars, redsocks/iptables/sing-box configs, DNS/DoH and IPv6 rules

- [ ] Build a provider-by-provider matrix for direct IPv4, IPv6, DNS, DoH bypass, UDP/WebRTC, process bypass, and reboot persistence.
  Current state: source contracts reviewed; live packet/reboot evidence pending.
- [ ] Capture packets only in read-only diagnostic mode; correlate observed egress with DB lease ownership.
- [ ] Finish Wipter post-fix proof and mark every non-tested provider `unverified`.
- [ ] Do not claim zero-leak until packet and reboot evidence exists for the relevant runtime.

### Task 5: UI/UX and browser interaction sweep

**Files:**
- Create: `docs/evidence/ui-ux-browser-sweep-2026-09-10.md`
- Inspect/fix only when confirmed: `app/templates/`, `app/static/js/app.js`, `app/static/css/style.css`
- Create tests: `tests/test_ui_audit_regressions.py` when a defect is fixed

- [ ] Use Chrome profile 40 and the already authenticated CashPilot tabs; capture full-page screenshots and DOM/text evidence for every navigation item and settings subsection.
- [ ] Click every non-destructive button, test valid/invalid/empty inputs, loading states, error states, retry states, pagination, filters, and responsive layout.
- [ ] Verify labels, grouping, terminology, status semantics, stale-data indicators, empty states, confirmation dialogs, keyboard focus, contrast, touch target size, and no horizontal overflow.
- [ ] Test Proxy Pool, EarnApp accounts, payments/PayPal, collectors, workers, provider pages, runtime settings, reconciliation, payouts, and system settings.
- [ ] Fix only reproducible UI/logic defects; preserve destructive controls and require two confirmations.

### Task 6: Full automated verification

**Files:**
- Update: relevant regression tests and evidence documents

- [x] Run targeted tests for every changed subsystem.
- [x] Run full pytest (`2761 passed, 8 skipped`), source Ruff, route enumeration, and security-header checks. Repository-wide formatting still includes pre-existing drift/user artifacts.
- [ ] Wait for PR checks; do not merge while required checks are pending or failing.
- [ ] Verify UI and worker image publication independently by registry manifest and in-image version/content checks.

### Task 7: Findings report and live-test gate

**Files:**
- Create: `docs/evidence/pre-live-findings-2026-09-10.md`
- Update: `docs/superpowers/plans/2026-09-10-earnapp-production-readiness.md`

- [ ] Report completed work, confirmed defects fixed, unresolved findings, policy changes needed, and evidence links.
- [x] Produce a complete CashPilot capability map: providers, runtimes, workers, proxy pool, leases, accounts, collectors, payments, heartbeat, recovery, lifecycle, reconciliation, security, UI, CI/CD, and external dependencies.
- [ ] Assign each finding one status: `fixed`, `verified`, `unverified`, `blocked`, or `requires user decision`.
- [ ] Only after the report is reviewed and all required gates pass, propose a separate live-canary plan.

## Exit Gates

- No unexplained source changes.
- No high-confidence security finding remains unmitigated for the planned live scope.
- UI sweep has evidence for every in-scope page and control.
- Required backend tests, full suite, lint, build, and CI pass.
- Provider network claims match evidence; unknown remains unknown.
- No live mutation occurs during pre-live audit.
