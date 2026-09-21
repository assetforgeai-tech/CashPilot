# Retained Behavior Matrix

Comparison basis: clean integration worktree at `origin/main` versus
`repo-spide-release-20260916`. No migration code is imported by this matrix.

| requirement | current canonical behavior | migration-source behavior | evidence | decision |
|---|---|---|---|---|
| topology/count planning | `provider_topology.py` uses explicit lanes, public-IP slots, and proxy capacity gates | Adds/adjusts topology and provider policy tests | canonical module; migration diff/stat | retain canonical; review migration deltas |
| proxy eligibility/lease/release/sticky ownership | DB lease/release APIs; EarnApp has account/node route helpers | Large DB additions for CAS, sticky routes, and reconciliation | `app/database.py` symbols; migration diff | retain only after slice review |
| generic recovery hold | EarnApp recovery module exposes hold and replacement-ticket flow | Adds staged recovery/fault-injection paths | `app/earnapp_recovery.py`; migration files | retain baseline; review additions |
| EarnApp token/account/link/lifecycle | Account routes, account lock/queue, collection and lifecycle modules exist | Adds account operation queue, health, staged recovery, and asset changes | `app/earnapp_canary.py`, `earnapp_collection.py`; migration tests | review as one isolated slice |
| provider runtime renderer | `provider_runtime.py`, `earnapp_runtime.py`, `orchestrator.py` define catalog/render validation | Adds proxy runtime/network audit and renderer changes | canonical runtime modules; migration diff | retain contract; no blind replacement |
| DNS/DoH/IPv6/UDP/direct fallback | Runtime contracts declare tunneled DNS, explicit IPv6/UDP, fail-closed, no fallback | Adds network audit/sidecar tests and policy changes | `provider_runtime.py`, `singbox_config.py`; migration files | unverified live behavior; require focused review |
| watchdog/reboot persistence | Worker heartbeat and runtime inventory paths exist | Adds watchdog/health/reboot-oriented tests and logic | `api_worker_heartbeat`; migration diff | review with worker/runtime slice |
| collectors/payment/account pools | Collector factory and EarnApp payment/PayPal pool APIs exist | Adds/extends collectors, payment pool, and account pool tests | `app/collectors`, `earnapp_collection.py`, DB PayPal APIs | retain existing APIs; review changed adapters |
| dashboard presentation | API/UI routes expose provider/proxy/account data | Adds frontend wiring/settings and reconciliation views | `app/static/js/app.js`, routers; migration diff | review UI slice; no visual claim yet |
| worker authentication/identity | Worker API key verification, confirmed-worker checks, runtime asset scoping | Adds worker/runtime authority and asset handling | `worker_api.py:_verify_api_key`, `main.py:_require_confirmed_worker` | security-review before import |
| release/GHCR/Azure bootstrap | Catalog/config and worker routes exist; exact production bootstrap equivalence not proven here | Adds Azure startup tests/evidence and service changes | migration evidence paths; no secret values | unverified; classify as review-required |

## Evidence discipline

`unverified` means the current files do not prove the behavior. Provider
dashboard screenshots, runtime logs, or historical chat claims cannot silently
upgrade a row to retained behavior. Each future import must name the exact code,
focused test, and sanitized evidence that changes its decision.
