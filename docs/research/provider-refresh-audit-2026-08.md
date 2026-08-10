# Provider refresh audit - 2026-08-10

Status: implementation snapshot. Source priority is official site/docs/dashboard/API/GitHub first. No hidden dashboard/API fields are guessed.

## Changes applied

| Provider | Catalog action | Source basis | Notes |
|---|---|---|---|
| bytelixir | updated | <https://bytelixir.com> public pages | Windows/Android only, 50 Mbps minimum, $2 public minimum payout claim, typical $2-10/month public claim. No public API found. |
| speedshare | revived from dead to active | <https://speedshare.app> and liveness check | Official site/dashboard now answer. Keep manual collector; no public earnings API found. |
| wipter | revived from dead to active | <https://wipter.com> and liveness check | Official site now answers. Keep scrape/manual dashboard model; no public API found. |

## Audit matrix

| Provider | Status | Client model | Collector | Verdict |
|---|---|---|---|---|
| bytebenefit | active | app only | manual | needs_user_info: no public API/collector docs found. |
| bytelixir | active | Windows/Android app | manual | updated; collector remains cookie scrape/manual because no official API shape found. |
| ebesucher | active | browser/surfbar | manual | keep; official model remains browser traffic exchange. |
| packetstream | active | desktop client / CID | scrape | updated; current public setup is desktop-client-first, not app-only. |
| proxybase | active | Docker/app | manual | keep; existing vendor/test guard says VPS/datacenter accepted. |
| proxybase-xyz | active | Docker CLI marketplace | manual | keep; proxy inventory-like seller network, but still an earning provider entry until proxy-pool integration is designed separately. |
| spide | active | app only | manual | keep; official terms already drive residential/one-IP warning. |
| urnetwork | active | Docker/app | manual | keep; no public earnings API found. |
| earncc | broken | app/site | manual | keep broken; official site/connectivity not reliable. |
| packetshare | dead | legacy Docker/app | manual | keep dead; no verified current earning path. |
| peer2profit | dead | legacy Docker/app | api | keep dead; no verified current earning path. |
| speedshare | active | app/community Docker | manual | updated; active but no official Docker/API. |
| wizardgain | broken | Docker/app | manual | keep broken; official site/connectivity not reliable. |
| dawn | active | browser extension/hardware | scrape | needs_user_info: dashboard/API sample required. |
| gradient | active | browser extension | scrape | needs_user_info: dashboard/API sample required. |
| nodepay | active | mobile app + dashboard | scrape | updated; current public site centers on app/dashboard rewards rather than the old extension-first copy. |
| teneo | active | browser extension + Beacon app | scrape | updated; Beacon now appears on Android/iOS/Mac/Windows/Linux. |
| deeper-network | active | proprietary hardware | manual | keep; not a VPS/server container target. |
| nodle | active | mobile app | manual | keep; mobile-only earning path. |
| passiveapp | active | app only | manual | needs_user_info: current API/export docs required. |
| sentinel-dvpn | active | node software | manual | keep; on-chain/manual model. |
| theta-edge | active | desktop app | manual | keep; no headless Docker/API found. |
| uprock | active | extension/mobile | manual | needs_user_info: current API/export docs required. |
| flux | active | host node | manual | keep; compute/stake node, no CashPilot Docker collector change. |
| golem | active | Yagna provider | api | keep; local Yagna API model. |
| ionet | active | GPU provider | manual | needs_user_info: current worker/API docs or sample response required. |
| nosana | active | GPU provider | api | keep; Solana/explorer API model. |
| salad | active | Windows app | api | keep; cookie API collector already exists. |
| vast-ai | active | GPU marketplace | api | keep; API-key model. |
| bitping | active | Docker/app | api | keep; API collector already exists. |
| earnapp | active | app/Docker prohibited by ToS | api | keep; collector exists, deploy warning remains required. |
| earnfm | active | Docker/client | api | keep; Supabase collector exists. |
| honeygain | active | Docker/app | api | keep; collector exists. |
| iproyal | active | Docker/app | api | keep; collector exists. |
| mysterium | active | Docker/VPN node | api | keep; direct egress and TequilAPI collector already set. |
| proxylite | active | Docker/app | api | keep; user-id API model. |
| proxyrack | active | Docker/app | api | keep; API-key collector exists. |
| repocket | active | Docker/app | api | keep; Firebase collector exists. |
| traffmonetizer | active | Docker/app | api | keep; token collector exists. |
| proxies-sx | beta | SDK Docker peer | api | keep; recently added API collector/per-node earnings. |
| storj | active | Docker/storage node | api | keep; local dashboard API collector and direct egress already set. |
| grass | active | extension/app | api | keep; token collector exists. |
| helium | active | hardware/network | api | keep; on-chain/API model. |
| presearch | active | Docker node | api | keep; node dashboard model. |
| titan | active | app | api | needs_user_info: current dashboard/API sample required. |
| anyone-protocol | active | Docker relay | auto | keep; reward contract collector exists. |
| blockmesh | dropped | extension | scrape | keep dropped; not reintroduced without current official docs. |
| gaganode | dropped | app | api | keep dropped; no verified current safe earning path. |
| koii | broken | app/node | manual | keep broken; official access/connectivity not reliable. |
| network3 | broken | app/node | manual | keep broken; official access/connectivity not reliable. |
| wipter | active | app only | scrape | updated; active but no public API found. |

## Needs user info

Provide official docs, dashboard export, or redacted API response before adding collectors for: `bytebenefit`, `dawn`, `gradient`, `passiveapp`, `uprock`, `ionet`, `titan`.

Provider fields with conflicting or insufficient official public data: `bytelixir` payout threshold history, `proxybase-xyz` buyer/seller proxy-inventory split, `urnetwork` earnings API, `speedshare` official collector/API, `nodepay` current rewards model, `teneo` current payout shape.
