# Provider refresh audit - 2026-08-11

Status: implementation snapshot. Source priority is official site/docs/dashboard/API/GitHub first. No hidden dashboard/API fields are guessed.

Catalog source-of-truth after deletion batch: 21 providers total; 16 bandwidth,
5 DePIN; 15 Docker deployable; 15 collectors.

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
| wipter | revived from dead to active | <https://wipter.com> and liveness check | Official site now answers. Keep scrape/manual dashboard model; no public API found. |

## 2026-08-11 bandwidth dashboard batch

| Provider | Visible state | Verdict |
|---|---|---|
| bitping | logged-in choose page; app dashboard + nodes paths visible | current model confirmed; no code change needed |
| earnapp | logged-in dashboard, current balance visible | current model confirmed; keep Docker warning |
| earnfm | new dashboard base `https://app.earn.fm/` is visibly logged in; Home shows balance and total bandwidth shared, Payout shows residential/datacenter/referral/available/pending buckets, More shows the UUID API key | setup and payout URLs updated |
| iproyal | new dashboard `https://dashboard.pawns.app/` logged in; app download, balance, $5 threshold, Internet Sharing/Cashout menu visible | dashboard URL updated |
| spide | official install page exposes Linux CLI download; dashboard has Register Device form posting `title` + `device_key` to `/api/v1/device/create` with bearer token from `_token` cookie | automation is feasible: start CLI, parse Device key, register through dashboard API |
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
| uprock | no dashboard node; install page only, runtime is seed/profile based | keep manual; no public node dashboard or Docker flow confirmed |
| wipter | public site confirms desktop/mobile app, Linux included, login state persists, Docker restart-always friendly, and direct wallet connect | current model confirmed; keep scrape/manual dashboard model |

## Audit matrix

| Provider | Status | Client model | Collector | Verdict |
|---|---|---|---|---|
| packetstream | active | desktop client / CID | scrape | updated; current public setup is desktop-client-first, not app-only. |
| proxybase | active | Docker/app | manual | keep; existing vendor/test guard says VPS/datacenter accepted. |
| proxybase-xyz | active | Docker CLI marketplace | manual | keep; proxy inventory-like seller network, but still an earning provider entry until proxy-pool integration is designed separately. |
| spide | active | Linux CLI + dashboard registration | manual | automated as a two-phase setup: CLI emits Device key, then CashPilot registers it with `POST /api/v1/device/create` using the saved dashboard credential. |
| urnetwork | active | Docker/app | manual | keep; no public earnings API found. |
| dawn | active | browser extension/hardware | scrape | current dashboard is live; logged-in account shows connection quality, points, streak, referrals, and epoch rewards. |
| uprock | active | extension/mobile | manual | seed/profile bundle flow confirmed; keep collector manual until a public API shape is verified. |
| bitping | active | Docker/app | api | keep; API collector already exists. |
| earnapp | active | official app / Docker prohibited | api | updated; official earning model is now pay-per-time, with Docker/VM/hosting still prohibited. Deploy warning remains required. |
| earnfm | active | Docker client / UUID API key | api | dashboard base URL updated to app.earn.fm; visible dashboard confirms balance, bandwidth totals, payout buckets, and API key location under More. |
| iproyal | active | Docker/app | api | dashboard URL updated to dashboard.pawns.app; collector exists. |
| mysterium | active | Docker/VPN node | api | keep; direct egress and TequilAPI collector already set. |
| proxylite | active | Docker/app | api | keep; logged-in dashboard confirms Account ID based setup. |
| proxyrack | active | Docker/app | api | keep; API-key collector exists. |
| repocket | active | Docker/app | api | keep; Firebase collector exists. |
| traffmonetizer | active | Docker/app | api | keep; token collector exists. |
| proxies-sx | beta | SDK Docker peer | api | keep; recently added API collector/per-node earnings. |
| grass | active | extension/app | api | keep; token collector exists. |
| titan | active | app | api | logged-in dashboard shows per-device rows, daily history, TNTIP/USDC split, and paused-extension warning. |
| wipter | active | Docker/app | scrape | runtime is env-login based and restart-once friendly; no public API found. |

## Needs user info

Provide official docs, dashboard export, or redacted API response before adding collectors for: `uprock`.

Provider fields with conflicting or insufficient official public data: `proxybase-xyz` buyer/seller proxy-inventory split, `urnetwork` earnings API.

## Cross-cutting follow-up

- Restart ownership decision: systemd supervises only core services (`docker`, `cashpilot-ui`, `cashpilot-worker`); provider containers stay owned by CashPilot/Docker and should use Docker `restart: always`.
- MYST is a separate direct-wallet lane: funded wallet leasing, password/MMN setup, and wallet rotation are its own module, not a generic bandwidth provider.
- Grass/Uprock are seed/profile style runtimes. EarnApp is cookie-based. Spide is device-key registration after first CLI start. IPRoyal uses the official Pawns CLI Docker image. Wipter uses env-login with post-login restart.
- CashPilot deploy path and compose export now set provider containers to `restart: always`. Core systemd remains for CashPilot worker/UI only, not one unit per provider.

## 2026-08-11 normalization planning notes

### Proxy Manager final reference

Reference clone kept outside the repo:
`D:\1. WORK_true\CashPilot\secret\external-repos\proxy-manager-final`.

Confirmed reusable MYST pieces:

- DB table: `myst_wallets`.
- Wallet states: `AVAILABLE`, `LEASED`, `QUARANTINED`.
- Funding states: `FUNDED`, `UNFUNDED`.
- Admin API: import, list/search, release, quarantine, mark funded/unfunded, export.
- Client direct API: request, ack, heartbeat, release.
- Raw wallet storage: encrypted by `MYST_WALLET_ENCRYPTION_KEY`.
- Admin list returns metadata only; raw wallet material is returned only by export or active client lease.
- Direct allocation key: `client_secret + fleet_id + host_id + client_instance + public_ip`.
- Direct public IP conflict is explicit: `MYST_DIRECT_PUBLIC_IP_IN_USE`.
- Direct IP change is explicit: `MYST_WALLET_REBIND_REQUIRED`.
- Unfunded detection accepts evidence like `payment_required`, `deposit_required`, `Unregistered`, `Deposit 0.15 MYST`, and then marks wallet `UNFUNDED`.

CashPilot module shape:

- Add separate menu `MYST Wallet`, not under provider catalog.
- Add `myst_wallets` migration/model/API from Proxy Manager final with CashPilot auth/DB conventions.
- Worker direct runtime requests wallet from server, writes wallet material locally with mode `0600`, imports into MYST, sets dashboard password, sets MMN API key, starts `mysteriumnetwork/myst:latest` with host networking, TUN, `NET_ADMIN`, UDP port range, and `restart: always`.
- Worker heartbeats wallet status plus redacted evidence; server keeps wallet leased while direct client is alive.
- On payment-required evidence, worker deletes local wallet material, stops/recreates MYST runtime, requests another funded wallet, retry capped.

### Provider auth normalization

Provider setup credentials should be separated by purpose:

- `deploy.credentials[]`: material needed on worker at install/runtime, for example CID, device token, seed bundle, cookie bundle, wallet lease.
- `collector.credentials[]`: material needed only by server-side earnings collectors, for example dashboard token, API key, bearer token, cookie.
- `dashboard.credentials[]`: optional helper metadata for browser-audit flows, never required for headless worker deploy.

Chrome profile login is an audit/source-discovery tool, not a stable runtime dependency. Runtime should prefer explicit API key/token/cookie/seed material stored in CashPilot Settings or server-managed secret inventory. Provider-specific auto-refresh can be added only after that provider's dashboard/API flow is proven.

### Spide automation decision

Spide should be automated as a two-phase worker flow:

1. Start the official Linux CLI container/process.
2. Parse stdout for the `Device key`.
3. Register that key against Spide dashboard API `POST /api/v1/device/create` using server-stored dashboard credential.

Open design point: Spide dashboard credential should probably be stored as a collector/setup credential entered in Settings first. Chrome profile extraction can remain an audit helper, not deploy default.

### Grass multi-node test

Approved test: on `vps-test-sing`, create two trial Grass nodes with the same seed/profile material and blank `device_id` / `browser_id`, then compare dashboard after a few minutes. Do not normalize Grass multi-node install until this is verified by dashboard or runtime evidence.

Live probe on 2026-08-11: two containers on `vps-test-sing` with the same seed and `GRASS_RESET_DEVICE_ID=true` / `GRASS_RESET_BROWSER_ID=true` both reached local `CONNECTED` state. `device_id` regenerated distinctly per node, but `browser_id` remained identical. The visible dashboard still showed no networks and the seed token returned `401` from `https://api.getgrass.io/activeDevices`, so dashboard-level multi-node proof remains inconclusive. Keep Grass multi-node defaults unresolved until a fresh seed/dashboard token for the same account verifies `activeDevices`.
