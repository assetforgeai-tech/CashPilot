# Provider refresh audit - 2026-08-11

Status: implementation snapshot. Source priority is official site/docs/dashboard/API/GitHub first. No hidden dashboard/API fields are guessed.

## Logged-in dashboard workflow

When public docs do not expose setup tokens, CIDs, device lists, or API shapes,
use the local Chrome profile already logged in as `assetforgeai@gmail.com`.
Dashboard work is setup-safe only: read setup, device, earnings, and API
responses; do not touch payout, billing, password, security, or purchases.
Redacted findings stay outside the repo under
`D:\1. WORK_true\CashPilot\secret\providers\<slug>\` as dashboard notes, API
samples, and screenshots. Repo changes are made only after the dashboard shape
or official docs make the update certain.

## Changes applied

| Provider | Catalog action | Source basis | Notes |
|---|---|---|---|
| bytelixir | updated | <https://bytelixir.com> public pages | Windows/Android only, 50 Mbps minimum, $2 public minimum payout claim, typical $2-10/month public claim. No public API found. |
| speedshare | revived from dead to active | <https://speedshare.app> and liveness check | Official site/dashboard now answer. Keep manual collector; no public earnings API found. |
| wipter | revived from dead to active | <https://wipter.com> and liveness check | Official site now answers. Keep scrape/manual dashboard model; no public API found. |

## 2026-08-11 bandwidth dashboard batch

| Provider | Visible state | Verdict |
|---|---|---|
| bitping | logged-in choose page; app dashboard + nodes paths visible | current model confirmed; no code change needed |
| earnapp | logged-in dashboard, current balance visible | current model confirmed; keep Docker warning |
| earnfm | new dashboard base `https://app.earn.fm/` is visibly logged in; screenshot shows dashboard balance, total bandwidth shared, Home/Payout/Referral/More menu, and download-app warning | URL updated; needs API sample only before collector changes |
| honeygain | new/current dashboard `https://dashboard.honeygain.com/` logged in; balance, payout threshold, earnings, active device count visible | current model confirmed |
| iproyal | new dashboard `https://dashboard.pawns.app/` logged in; app download, balance, $5 threshold, Internet Sharing/Cashout menu visible | dashboard URL updated |
| proxylite | `https://lk.proxylite.ru/` logged in; Account ID, balance, devices, payouts menu visible | current model confirmed |
| proxyrack | logged-in dashboard with device rows and balance | current model confirmed |
| repocket | logged-in dashboard with offers/bandwidth area | current model confirmed |
| traffmonetizer | logged-in dashboard with token/balance page | current model confirmed |
| proxies-sx | public home page visible | current peer-SDK model confirmed |
| packetstream | logged-in dashboard with balance/device activity | current model confirmed |
| proxybase | logged-in peer dashboard with devices, balance, access token | current model confirmed |

## 2026-08-11 DePIN dashboard batch

| Provider | Visible state | Verdict |
|---|---|---|
| dawn | logged-in rewards dashboard; connection quality connected, total/epoch/referral points visible | current dashboard model confirmed |
| gradient | login page only | needs logged-in session or API sample |
| nodepay | V2 upgrade wall visible | no API/collector change without completing upgrade |
| teneo | cert authority error on dashboard URL | do not bypass; needs safe/valid URL or user-side resolution |
| titan | logged-in dashboard; TNTIP/USDC, tasks, paused extension warning visible | current dashboard model confirmed |
| passiveapp | logged-in dashboard; earnings, $5 threshold, devices, traffic chart, download link visible | update dashboard URL; manual tracking only |

## Audit matrix

| Provider | Status | Client model | Collector | Verdict |
|---|---|---|---|---|
| bytebenefit | active | Windows/Android app | manual | updated; current public setup is app-only, min payout $3. No public API/collector docs found. |
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
| dawn | active | browser extension/hardware | scrape | current dashboard is live; logged-in account shows connection quality, points, streak, referrals, and epoch rewards. |
| gradient | active | browser extension | scrape | current public dashboard still logged out in this browser session. |
| nodepay | active | mobile app + dashboard | scrape | logged-in dashboard currently shows the V2 upgrade wall. |
| teneo | active | browser extension + Beacon app | scrape | dashboard URL hit cert error in this browser session; no new collector/API shape confirmed. |
| deeper-network | active | proprietary hardware | manual | keep; not a VPS/server container target. |
| nodle | active | mobile app | manual | keep; mobile-only earning path. |
| passiveapp | active | app only | manual | logged-in dashboard shows earnings, threshold, devices, traffic shared, referrals, and download links. |
| sentinel-dvpn | active | node software | manual | keep; on-chain/manual model. |
| theta-edge | active | desktop app | manual | keep; no headless Docker/API found. |
| uprock | active | extension/mobile | manual | needs_user_info: current API/export docs required. |
| flux | active | host node | manual | keep; compute/stake node, no CashPilot Docker collector change. |
| golem | active | host Yagna/Docker provider | api | updated; current setup is host-level provider install, not a single CashPilot-managed image. |
| ionet | active | dashboard-driven GPU worker | manual | updated; current worker onboarding is dashboard-driven. Needs API/sample response for collector. |
| nosana | active | GPU provider | api | keep; Solana/explorer API model. |
| salad | active | Windows app | api | keep; cookie API collector already exists. |
| vast-ai | active | GPU marketplace | api | keep; API-key model. |
| bitping | active | Docker/app | api | keep; API collector already exists. |
| earnapp | active | official app / Docker prohibited | api | updated; official earning model is now pay-per-time, with Docker/VM/hosting still prohibited. Deploy warning remains required. |
| earnfm | active | Docker client / UUID API key | api | dashboard base URL updated to app.earn.fm; visible dashboard confirms balance and bandwidth totals, but collector remains email/password because no API-key balance contract was confirmed. |
| honeygain | active | Docker/app | api | keep; logged-in dashboard confirms balance/earnings/device views. |
| iproyal | active | Docker/app | api | dashboard URL updated to dashboard.pawns.app; collector exists. |
| mysterium | active | Docker/VPN node | api | keep; direct egress and TequilAPI collector already set. |
| proxylite | active | Docker/app | api | keep; logged-in dashboard confirms Account ID based setup. |
| proxyrack | active | Docker/app | api | keep; API-key collector exists. |
| repocket | active | Docker/app | api | keep; Firebase collector exists. |
| traffmonetizer | active | Docker/app | api | keep; token collector exists. |
| proxies-sx | beta | SDK Docker peer | api | keep; recently added API collector/per-node earnings. |
| storj | active | Docker/storage node | api | keep; local dashboard API collector and direct egress already set. |
| grass | active | extension/app | api | keep; token collector exists. |
| helium | active | hardware/network | api | keep; on-chain/API model. |
| presearch | active | Docker node | api | keep; node dashboard model. |
| titan | active | app | api | logged-in dashboard shows per-device rows, daily history, TNTIP/USDC split, and paused-extension warning. |
| anyone-protocol | active | Docker relay | auto | keep; reward contract collector exists. |
| blockmesh | dropped | extension | scrape | keep dropped; not reintroduced without current official docs. |
| gaganode | dropped | app | api | keep dropped; no verified current safe earning path. |
| koii | broken | app/node | manual | keep broken; official access/connectivity not reliable. |
| network3 | broken | app/node | manual | keep broken; official access/connectivity not reliable. |
| wipter | active | app only | scrape | updated; active but no public API found. |

## Needs user info

Provide official docs, dashboard export, or redacted API response before adding collectors for: `bytebenefit`, `gradient`, `uprock`, `ionet`.

Provider fields with conflicting or insufficient official public data: `bytelixir` payout threshold history, `proxybase-xyz` buyer/seller proxy-inventory split, `urnetwork` earnings API, `speedshare` official collector/API, `nodepay` current rewards model, `teneo` current payout shape.
