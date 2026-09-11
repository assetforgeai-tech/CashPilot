# Static UI inventory — 2026-09-11

Chrome interaction evidence remains unavailable because the connector returns `Codex auth token is unavailable`. This inventory is static evidence only and does not replace browser testing.

## Template coverage

- 14 HTML templates under `app/templates/`.
- Navigation/content surfaces: auth, onboarding, dashboard, catalog, fleet, MYST Wallet, NKN Wallet, payouts, proxy pool, proxy providers, service detail, setup, settings, base layout.
- Static scan found 168 form controls (`button`, `input`, `select`, `form`) and 22 root navigation links.

## Controls requiring browser verification

- Destructive: remove service, remove worker, delete selected/dead/all proxy pool entries, wallet/account deletion where present.
- Proxy Pool: protocol selector, provider/location/IP-type/EarnApp/duplicate filters, recheck, metadata refresh, EarnApp check, exports, import, pagination, delete confirmations.
- Settings: auto-deploy, runtime CPU/RAM, platform policy, collector/account controls, provider credentials, recovery and payout controls.
- Fleet: API-key reveal/copy, search, power settings, worker removal, pagination.
- Service detail: deploy/start/restart/stop/remove/logs.
- Wallets: file import, state/funding filters, search, exports.

## Static risks to verify in Chrome

1. Every destructive action must show two confirmations and must not execute on cancel.
2. Every async action must expose loading, success, failure, and retry states without duplicate submissions.
3. Every generated table must preserve escaped text, keyboard sorting/focus, pagination boundaries, and empty states.
4. Inputs must reject empty, malformed, duplicate, out-of-range, and oversized values with visible field-level errors.
5. Mobile viewport must not introduce horizontal overflow or hide destructive controls outside the viewport.

## Source-scan note

Several buttons omit an explicit `type` attribute. Most are outside a form and
therefore do not currently submit anything; form-contained controls must still
be checked in the browser before changing markup. No blanket edit was made
without interactive reproduction.

## Status

`UNVERIFIED_BROWSER`: static coverage is recorded; live click/input/screenshots are still required.
