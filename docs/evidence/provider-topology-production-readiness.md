# Provider topology production readiness

Date: 2026-09-12

## Read-only server preflight

- CashPilot worker container: healthy.
- CashPilot UI container: healthy.
- Existing Wipter runtime and managed egress sidecar: running.
- Server upgraded to `v1.37.0`; UI and worker containers healthy.
- Azure workers `20.187.79.110` and `20.210.93.220` upgraded to worker `1.37`
  with `restart=always`, original `/data` volume, and healthy status.
- East Asia worker reports 10/10 NKN LXD direct slots running.
- Read-only plan preflight: Earn.fm hybrid `20/20` deployable (10 direct + 10
  proxy); EarnApp proxy-only `10/10` deployable; no pending capacity.
- No mutation was performed during this inspection.

## Code gates

- Direct-only, hybrid, and proxy-only topology contracts are present.
- Runtime catalog now exposes `direct_required`, `proxy_required`, and explicit
  fail-closed fallback flags; topology summaries expose direct/proxy free and
  blocked capacity independently.
- Proxy routes fail closed when a proxy is absent or cannot satisfy required UDP.
- Provider plan API exposes compute, disk, ports, IPv4-slot, and proxy-capacity preflight.
- PR `#306` merged as `604365d`.
- PR `#307` adds the preflight API and compose release pin correction; CI pending.
- Commit `67a80d9` adds the lane-aware topology contract and focused regression
  coverage (`17 passed` in `tests/test_provider_topology.py`; `60 passed` across
  topology, modes, capacity, egress, and lifecycle policy suites).

## Outstanding live gates

- Deterministic proxy reservation per worker/provider/lane/slot.
- Live direct-only, hybrid, and proxy-only deployment evidence.
- Per-container IPv4/IPv6/DNS/DoH/UDP/direct-fallback leak matrix.
- Lease, release, sticky ownership, rotation, reboot, and failure-isolation evidence.
- Release digest deployment verification.

## Current live verification note (2026-09-13)

- The East Asia worker responds healthy and exposes 10/10 route-ready IPv4 slots.
- Its systemd unit still builds local `assetforgeai/cashpilot-worker:dev`; the
  running container reports `CASHPILOT_VERSION=1.39.0`. This is a deployment
  drift, not evidence for the released `1.40` artifact.
- The authenticated `/api/network/slots` endpoint returned `401` when called
  without the worker's issued key. No guessed or extracted secret was used.
- Therefore live deployment/restart/rotation evidence remains pending until the
  worker is upgraded through its normal authenticated deployment path.

## Authenticated slot evidence (2026-09-13)

- East Asia worker `20.187.79.110`: authenticated slot endpoint returned 10
  slots, all `route_ready=true`; sampled direct egress matched `ipv4-001`,
  `ipv4-005`, and `ipv4-010`.
- Japan East worker `20.210.93.220`: authenticated slot endpoint returned 10
  slots, all `route_ready=true`; health endpoint returned HTTP 200.
- Direct slot containers use dedicated Docker bridge networks and Docker's local
  resolver. This proves direct-slot routing only; it does not prove proxy-only
  or hybrid behavior, nor DoH/DoT/UDP leak absence.
- Both workers still report running worker image `1.39`; release artifact `1.40`
  is not yet deployed to either live worker.

## Worker upgrade correction (2026-09-13)

- Japan East stale container `cashpilot-worker` was verified to use the
  authoritative `cashpilot_cashpilot_worker_data` volume before replacement.
- The stale unlabeled `1.39` container was stopped and removed; no provider
  container or data volume was touched.
- Compose recreated the worker as
  `ghcr.io/assetforgeai-tech/cashpilot-worker:1.40`; runtime reports `1.40.0`.
- `/api/health` returned HTTP 200, restart policy is `always`, and
  `cashpilot-worker.service` is active.
- The old duplicate volume `cashpilot-worker_cashpilot_worker_data` remains
  retained for rollback/comparison. Worker identity continuity hashes were
  recorded without exposing key contents.
- This proves worker upgrade/restart persistence only; provider live lane and
  leak evidence remain outstanding.
