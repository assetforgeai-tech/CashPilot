# Azure Network/Provider Audit - 2026-09-14

The read-only reconciliation endpoint was queried for both Azure workers. EarnApp and several fully instrumented lanes report proxy egress and fail-closed controls. Other lanes report `missing observed proxy egress` or unverified direct DNS/IPv6/fallback controls; those findings are intentionally not treated as safe.

No network mutation was performed. A full per-lane probe matrix remains pending.

Current reconciliation is not sufficient for a production claim: `proxies-sx`, `proxybase`, `proxyrack`, `repocket`, `spide`, `urnetwork`, `uprock`, and `wipter` have missing proxy-egress evidence on at least one worker; direct lanes for `earnfm`, `mysterium`, and `traffmonetizer` have unverified DNS/IPv6/direct-fallback controls.
