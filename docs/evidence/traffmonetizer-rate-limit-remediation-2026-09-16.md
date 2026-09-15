# Traffmonetizer rate-limit remediation (2026-09-16)

Live logs showed repeated login responses of `HTTP 429 Too Many Requests`.
The collector previously retried on every scheduled run without preserving the
provider's cooldown, producing avoidable repeated requests.

The collector now:

- reads and bounds `Retry-After` to 1--3600 seconds;
- supports HTTP-date `Retry-After` values;
- stores a process-local cooldown and skips requests during that window;
- returns a transient, user-safe error instead of treating the provider as a
  credential failure.

Tests: `1646 passed, 8 skipped` across the full suite; focused rate-limit tests
pass. No provider container was recreated.
