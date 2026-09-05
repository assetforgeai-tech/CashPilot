# EarnApp Platform Registry Implementation Plan

> **For agentic workers:** Execute this plan task-by-task with verification after each task.

**Goal:** Make EarnApp platform selection configurable per proxy country, improve proxy metadata and UDP evidence, document private runtime-image delivery, and keep orphan cleanup fail-closed.

**Architecture:** The server stores an explicit VN/non-VN platform policy and passes it to the existing sequential planner. Proxy probes persist UDP capability only when a SOCKS5 UDP ASSOCIATE succeeds; metadata remains evidence-based. Private runtime images remain operator-preloaded and are never pulled with credentials from the application.

**Tech Stack:** FastAPI, SQLite/aiosqlite, asyncio SOCKS5 probe, vanilla settings UI, pytest.

## Global Constraints

- Existing EarnApp node platform, identity, volume, lease and provider baselines are immutable.
- Default policy remains VN -> MacOS/iOS and non-VN -> Ubuntu.
- No live VPS mutation or automatic orphan deletion without exact CAS evidence and explicit approval.
- GHCR credentials never enter source, SQLite, logs or Docker specs.

### Task 1: Configurable platform policy

- Add policy parser and country filter in `app/earnapp_deploy.py`.
- Pass policy from server config to the sequential planner.
- Add settings checkboxes and preserve explicit false values in `app/static/js/app.js`.
- Add unit tests for defaults, all-platform selection and invalid empty country policy.

### Task 2: Proxy metadata and UDP evidence

- Extend `app/proxy_intelligence.py` to consume IPWHO connection/security fields.
- Add SOCKS5 UDP ASSOCIATE probe in `app/routers/proxies.py`.
- Persist `udp_ok` through `app/database.py` and generic probe evidence.
- Add isolated unit tests with a local asyncio SOCKS5 fixture.

### Task 3: Private runtime delivery contract

- Document private GHCR package setup and operator preload in `docs/earnapp-private-runtime.md`.
- Keep `image_delivery=operator_preload`; reject registry pulls in worker code.
- Add tests asserting no secret/token is present in generated runtime specs.

### Task 4: Orphan reconciliation safety

- Add read-only orphan inventory evidence to the EarnApp audit documentation.
- Do not auto-delete containers or volumes; require exact logical node, generation, device, sidecar, volume and egress match before any future adopt/remove operation.

### Task 5: Verification

- Run focused tests, full pytest, Ruff, compileall and `git diff --check`.
- Review diff for protected-provider changes and ensure no credentials were added.
