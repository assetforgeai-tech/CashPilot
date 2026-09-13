# Provider topology contract evidence

Date: 2026-09-13

The planner now models three provider shapes without cross-lane fallback:

| Topology | Direct capacity | Proxy capacity | Failure isolation |
| --- | --- | --- | --- |
| `slot_direct` | route-ready public IPv4 slots | none | direct lane only |
| `slot_proxy` | none | scoped eligible proxy capacity | proxy lane only |
| `slot_both` | route-ready public IPv4 slots | scoped eligible proxy capacity | direct and proxy lanes independent |

Hybrid deploy requests may set `direct_desired` and `proxy_desired` independently. An omitted target means all currently discovered capacity. A target above capacity creates blocked plans; it never borrows capacity from the other lane. Unknown proxy capacity remains pending and never becomes a direct or IPv4-shaped proxy plan.

Runtime leases, sticky ownership, and explicit account deletion remain separate operations. Dedicated adapters (`nkn`, `mysterium`) stay outside the generic slot planner.

Verification: `150 passed` across provider topology, API, slot deploy, and frontend wiring tests; `node --check app/static/js/app.js`; Ruff check and format applied to tracked changed files.

Still required before production readiness: browser control-flow verification, live hybrid/proxy-only lease and rotation evidence, reboot/orphan reconciliation evidence, and DNS/IPv6/UDP/DoH/DoT/direct-fallback probes for every lane.
