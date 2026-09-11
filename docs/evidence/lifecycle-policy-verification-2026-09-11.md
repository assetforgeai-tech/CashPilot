# Lifecycle policy verification — 2026-09-11

- EarnApp lifecycle policy tests: `tests/test_earnapp_lifecycle.py` and
  `tests/test_provider_lifecycle_policy.py` pass (`100` tests with proxy
  network/runtime coverage).
- Policy remains explicit: offline => in-place restart; banned => recreate;
  proxy-health/egress mismatch => rotate-and-recreate; positive usage clears
  recovery counters; earnings-cycle flatline waits through the cycle boundary
  before restart.
- The provider-wide helper returns `observe` for unknown/unconfigured
  providers, preventing unsupported generic mutation.
- This verifies source policy only. Live scheduler mutation and non-EarnApp
  provider behavior remain `unverified` until controlled canaries exist.
