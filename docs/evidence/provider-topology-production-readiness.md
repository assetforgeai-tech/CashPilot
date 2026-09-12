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
