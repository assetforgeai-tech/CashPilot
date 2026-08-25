# Proxy Metadata, Country Lease Key, And Summary UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Proxy Pool metadata enrichment observable and bounded, make ISO alpha-2 `country_code` the authoritative future EarnApp location key, and replace the unreadable metric-chip wall with responsive labeled summary groups.

**Architecture:** Keep generic liveness, EarnApp qualification, and metadata enrichment as separate contracts. The existing generic and EarnApp rechecks continue to discover authoritative egress IPs, but metadata lookup runs through a low-concurrency source-aware pipeline with reusable HTTP clients, country fallback, explicit failure counters, and a dedicated owner-only metadata refresh endpoint that can target one or a bounded set of proxy rows without rotating leases. The read model exposes a canonical country label derived from ISO code while preserving raw source evidence, and the Jinja/JavaScript view renders the current aggregate values in semantic summary groups.

**Tech Stack:** Python 3.12, FastAPI, SQLite/aiosqlite, httpx, Jinja2, browser JavaScript/CSS, pytest, Ruff, GitHub Actions, Docker.

## Global Constraints

- Do not modify protected provider runtime, worker code, provider identities, wallets, credentials, volumes, active assignments, scoped leases, or proxy sidecars.
- Do not recreate, pull, restart, or redeploy `cashpilot-worker`; release and deploy only `cashpilot-ui`.
- Do not run a live bulk generic or EarnApp recheck for metadata repair.
- Do not directly rewrite existing country/location/IP-type rows.
- Keep `country_code` as the authoritative ISO alpha-2 machine key; visible labels are derived presentation.
- Preserve duplicate-egress canonicalization and current EarnApp `CID_SET` lease eligibility.
- Live mutation order is one-IP canary first, then bounded metadata-only batches only when the canary persists correctly.
- Tests must be written and observed failing before production changes.

---

### Task 1: Capture The Verified Failure And Country Contract

**Files:**
- Create: `docs/research/proxy-pool-metadata-location-impact-map.md`
- Modify: `docs/research/proxy-pool-country-label-impact-map.md`

**Interfaces:**
- Consumes: live read-only diagnostics from `cashpilot-ui`, `lookup_ip_intelligence()`, `list_proxy_pool_page()`, and EarnApp lease selection.
- Produces: the exact failure evidence, protected boundaries, and authoritative country-code contract used by later tasks.

- [ ] **Step 1: Record the verified source failure**

Document the live inventory/count snapshot, `ipwho.is = 429`, all current `ipapi.is` endpoints failing to connect from the UI container, and the fact that current code converts these results to empty metadata without exposing a reason.

- [ ] **Step 2: Record the country contract**

Document `country_code` as ISO alpha-2 authoritative data for future EarnApp selection, `display_location` as a derived human label, and `country_name` / source payload as preserved evidence rather than a lease predicate.

- [ ] **Step 3: Record the mutation boundary**

State that this work cannot change proxy credentials, generic status, egress IP, EarnApp verdict, duplicate canonical row, assignment, lease, worker, or provider runtime. State that metadata refresh is one-IP canary then bounded batches.

### Task 2: Add Source-Aware Metadata Lookup

**Files:**
- Modify: `app/proxy_intelligence.py`
- Test: `tests/test_earnapp_proxy_probe.py`

**Interfaces:**
- Consumes: one validated public egress IP.
- Produces: an intelligence result plus non-secret source diagnostics with keys `country_code`, `country_name`, `location`, `geo_source`, `geo_confidence`, `ip_type`, `ip_type_source`, `ip_type_confidence`, and `lookup_status`.

- [ ] **Step 1: Write failing source-result tests**

Add tests proving: a rate-limited primary country source falls through to the next country source; a connect error is counted rather than silently discarded; quality lookup classifies residential/datacenter/proxy/VPN; and no-data results return explicit source/status counters without inventing metadata.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_earnapp_proxy_probe.py -k "intelligence" -q`

Expected: new assertions fail because the lookup exposes no diagnostics and has no independent country fallback after `ipwho.is`.

- [ ] **Step 3: Implement the minimal lookup pipeline**

Reuse one `httpx.AsyncClient` per bounded batch. Try country sources in order with exact source/status capture and `Retry-After` parsing; use the existing quality source chain for IP type. Stop source fan-out after explicit denial/rate-limit only for that source family, not across the unrelated country/quality family. Keep all payload normalization in pure helpers.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_earnapp_proxy_probe.py -k "intelligence" -q`

Expected: all intelligence tests pass.

### Task 3: Add A Metadata-Only Bounded Refresh

**Files:**
- Modify: `app/routers/proxies.py`
- Test: `tests/test_proxy_routes.py`

**Interfaces:**
- Consumes: optional proxy IDs, maximum batch size, and metadata concurrency.
- Produces: `{requested, unique, cache_hits, lookups, enriched, geo_enriched, type_enriched, unresolved, source_counts, failure_counts}` without running generic probes, EarnApp probes, rotation, or duplicate reconciliation.

- [ ] **Step 1: Write failing orchestration/API tests**

Test that metadata refresh deduplicates by egress IP, caps lookup concurrency independently of scheduler concurrency, reuses cached complete evidence, returns source/failure counters, refuses more than the bounded maximum, requires owner auth, and never calls generic probe, EarnApp probe, rotation, or lease code.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_proxy_routes.py -k "metadata_refresh or intelligence" -q`

Expected: failures because the metadata-only API and counters do not exist.

- [ ] **Step 3: Implement the bounded refresh path**

Add `POST /api/proxy-pool/metadata-refresh`. Default to selected IDs; require explicit bounded input; use metadata concurrency no greater than `2`; update only geo/IP-type fields when a source produced valid evidence; return explicit counters. Keep the current generic/EarnApp recheck call contracts unchanged except for using the same source-aware helper for their already-discovered egress IPs.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_proxy_routes.py -k "proxy_pool_recheck or metadata_refresh or intelligence" -q`

Expected: all selected tests pass.

### Task 4: Canonicalize The Country Read Model

**Files:**
- Modify: `app/database.py`
- Test: `tests/test_proxy_routes.py`

**Interfaces:**
- Consumes: persisted `country_code` plus optional raw `country_name`.
- Produces: `display_location` and location filter/export behavior keyed by canonical ISO code while retaining raw fields.

- [ ] **Step 1: Write failing country tests**

Seed `VN`, `Viet Nam`, and `Vietnam` evidence and prove they yield one visible label/filter bucket while `country_code=VN` remains unchanged. Test that a country-code filter matches every alias and that pending/unresolved status labels stay separate.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_proxy_routes.py -k "country or location_filter or proxy_pool_page" -q`

Expected: failure because the current read model prefers free-form `country_name` and exact-label filtering splits aliases.

- [ ] **Step 3: Implement a shared canonical display helper/read expression**

Use ISO alpha-2 code as the primary grouping/filter value and derive a stable human-readable label. Do not rewrite existing database rows. Ensure search, sorting, filter options, page rows, and filtered export use the same contract.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_proxy_routes.py -k "country or location or proxy_pool_page or proxy_pool_export" -q`

Expected: all selected tests pass.

### Task 5: Replace The Metric Chip Wall With Responsive Summary Groups

**Files:**
- Modify: `app/templates/proxy_pool.html`
- Test: `tests/test_frontend_wiring.py`

**Interfaces:**
- Consumes: the existing `counts` and `type_counts` envelope plus the metadata refresh result.
- Produces: labeled groups `Inventory & health`, `Assignment & availability`, `Egress & metadata`, `EarnApp qualification`, and `Protocol & IP type`.

- [ ] **Step 1: Write failing frontend tests**

Assert group headings and readable labels exist; raw underscore keys are not rendered; `Metadata pending`, `Egress unresolved`, `Eligible`, `Not checked`, `Residential`, and `Unknown` retain their values; the summary uses semantic list/definition markup; and the layout becomes one column at `375px`.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_frontend_wiring.py -k "proxy_pool" -q`

Expected: new summary assertions fail because the page renders a flat sequence of generic badges.

- [ ] **Step 3: Implement grouped summary UI**

Render fixed metric definitions instead of `Object.entries()`. Use tabular numerals, readable title case, short helper descriptions, accessible group headings, and status emphasis that does not rely on color alone. Add a metadata-refresh-selected control and display enriched/unresolved/source failure counts without exposing IPs or secrets.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_frontend_wiring.py -k "proxy_pool" -q`

Expected: all Proxy Pool frontend wiring tests pass.

### Task 6: Verify, Review, Ship, And Run The Live Canary

**Files:**
- Modify: `docs/ACTIVE_CONTEXT.md`
- Create: `docs/research/proxy-pool-metadata-location-live-closeout.md`

**Interfaces:**
- Consumes: Tasks 1-5.
- Produces: a merged PR, release, UI-only deployment, one-IP metadata canary, bounded metadata refresh evidence, and updated baseline documentation.

- [ ] **Step 1: Run complete local gates**

Run:

```bash
python -m pytest -q
python -m ruff check .
python -m compileall -q app tests
git diff --check
```

Expected: zero failures/errors.

- [ ] **Step 2: Review the diff against protected contracts**

Confirm no worker/provider/catalog/runtime/wallet/lease/credential files changed; generic and EarnApp eligibility predicates are unchanged; and no direct data migration/backfill exists.

- [ ] **Step 3: Commit, push, open PR, wait for CI, and merge**

The PR description must include root-cause evidence, the country-code contract, exact changed files, test evidence, and the UI-only deployment boundary.

- [ ] **Step 4: Release and deploy only `cashpilot-ui`**

Resolve the released UI digest, snapshot both live container IDs/start times/restart counts, recreate only `cashpilot-ui` using the current safe override procedure, then prove `cashpilot-worker` identity/start time/restart count are unchanged.

- [ ] **Step 5: Run one-IP metadata canary**

Choose one alive, unleased, canonical proxy with known egress and pending metadata. Call only the metadata-refresh endpoint for that ID. Verify persisted `country_code`, visible canonical Location, IP type/source timestamps, unchanged generic/EarnApp evidence, unchanged duplicate/lease state, and no secret output.

- [ ] **Step 6: Process bounded batches only after canary success**

Refresh pending metadata in bounded groups, recording enriched/unresolved/source failure counts after each group. Stop if failure rate or rate-limit evidence rises; do not fall back to generic/EarnApp recheck.

- [ ] **Step 7: Audit desktop and mobile**

At desktop and `375px`, verify readable summary grouping, no document-level horizontal overflow, table-only inner scrolling, canonical Location options/counts, IP-type counts, and no console/page errors.

- [ ] **Step 8: Record the closeout**

Update `docs/ACTIVE_CONTEXT.md` and the live closeout document with release/digest, container evidence, canary/batch results, remaining metadata gaps, and the explicit statement that protected providers and worker runtime were untouched.
