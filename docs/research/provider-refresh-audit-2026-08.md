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
| earnfm | new dashboard base `https://app.earn.fm/` is visibly logged in; Home shows balance and total bandwidth shared, Payout shows residential/datacenter/referral/available/pending buckets, More shows the UUID API key | setup and payout URLs updated |
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
| bytelixir | active | Windows/Android app | manual | updated; collector remains cookie scrape/manual because no official API shape found. |
| packetstream | active | desktop client / CID | scrape | updated; current public setup is desktop-client-first, not app-only. |
| proxybase | active | Docker/app | manual | keep; existing vendor/test guard says VPS/datacenter accepted. |
| proxybase-xyz | active | Docker CLI marketplace | manual | keep; proxy inventory-like seller network, but still an earning provider entry until proxy-pool integration is designed separately. |
| spide | active | app only | manual | keep; official terms already drive residential/one-IP warning. |
| urnetwork | active | Docker/app | manual | keep; no public earnings API found. |
| dawn | active | browser extension/hardware | scrape | current dashboard is live; logged-in account shows connection quality, points, streak, referrals, and epoch rewards. |
| passiveapp | active | app only | manual | logged-in dashboard shows earnings, threshold, devices, traffic shared, referrals, and download links. |
| uprock | active | extension/mobile | manual | needs_user_info: current API/export docs required. |
| bitping | active | Docker/app | api | keep; API collector already exists. |
| earnapp | active | official app / Docker prohibited | api | updated; official earning model is now pay-per-time, with Docker/VM/hosting still prohibited. Deploy warning remains required. |
| earnfm | active | Docker client / UUID API key | api | dashboard base URL updated to app.earn.fm; visible dashboard confirms balance, bandwidth totals, payout buckets, and API key location under More. |
| honeygain | active | Docker/app | api | keep; logged-in dashboard confirms balance/earnings/device views. |
| iproyal | active | Docker/app | api | dashboard URL updated to dashboard.pawns.app; collector exists. |
| mysterium | active | Docker/VPN node | api | keep; direct egress and TequilAPI collector already set. |
| proxylite | active | Docker/app | api | keep; logged-in dashboard confirms Account ID based setup. |
| proxyrack | active | Docker/app | api | keep; API-key collector exists. |
| repocket | active | Docker/app | api | keep; Firebase collector exists. |
| traffmonetizer | active | Docker/app | api | keep; token collector exists. |
| proxies-sx | beta | SDK Docker peer | api | keep; recently added API collector/per-node earnings. |
| grass | active | extension/app | api | keep; token collector exists. |
| titan | active | app | api | logged-in dashboard shows per-device rows, daily history, TNTIP/USDC split, and paused-extension warning. |
| wipter | active | app only | scrape | updated; active but no public API found. |

## Needs user info

Provide official docs, dashboard export, or redacted API response before adding collectors for: `uprock`.

Provider fields with conflicting or insufficient official public data: `bytelixir` payout threshold history, `proxybase-xyz` buyer/seller proxy-inventory split, `urnetwork` earnings API.
