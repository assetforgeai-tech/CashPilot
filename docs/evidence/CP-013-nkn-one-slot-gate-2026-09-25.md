# CP-013 NKN single-slot gate — 2026-09-25

## Scope and preflight

- User approved Stage 1: one NKN slot on worker `172243` (`cashpilot-prod-ea`), one AVAILABLE wallet; no global auto-deploy or other provider/resource mutation.
- CP-tqr merged in PR #512 at `91f337dd6c185467889386772d5138908d6e9a6c`, and its Beads dependency is closed.
- Read-only live check: target worker online, heartbeat fresh; 20 public IPv4 slots report `route_ready`; NKN beneficiary is configured; NKN LXD limits are 1 CPU / 1024 MiB; 26,020 AVAILABLE wallets, zero NKN leases and zero provider instances on target worker. `cashpilot_auto_deploy_enabled=false`.
- **Do not call the existing unscoped `POST /api/deploy/nkn` on this worker.** The current release iterates all 20 route-ready slots and would exceed Stage 1 approval.

## Change

- Add optional `slot_id` query parameter to the NKN deploy route and scheduler.
- With explicit `slot_id`, filter route-ready slots to that single exact slot before any wallet lease or worker command. Invalid or unready slots fail before mutation.
- Omitted `slot_id` retains the existing all-slot behavior for future, separately approved stages.
- No change to NKN wallet CAS, worker runtime, auto-deploy, or other provider path.

## Verification

- TDD RED: `test_nkn_deploy_restricts_canary_to_one_explicit_slot` failed with unexpected `slot_id` keyword before implementation.
- GREEN: 4 new targeted parameter cases passed.
- Focused NKN suite: `84 passed`.
- Full suite: `3612 passed, 7 skipped`.
- `uv run ruff check .`: pass; `uv run ruff format --check .`: pass (`572 files already formatted`).
- `python -m compileall -q app tests`: pass; `git diff --check`: pass.

## Deployment gate

- Code-only; no NKN node, wallet lease, Azure, VM, UI, worker, proxy, provider, or other runtime mutation in this step.
- After merge/CI/release: obtain explicit UI-only digest upgrade approval if required, verify live UI image and endpoint shape, then call `POST /api/deploy/nkn?worker_id=172243&slot_id=ipv4-001` once; verify response `slots=1`, wallet CAS, heartbeat, identity, dashboard/traffic and rollback. Stop after this one canary.
