# Provider topology production readiness

Date: 2026-09-12

## Read-only server preflight

- CashPilot worker container: healthy.
- CashPilot UI container: healthy.
- Existing Wipter runtime and managed egress sidecar: running.
- Worker runtime reports version `1.33.3`.
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
