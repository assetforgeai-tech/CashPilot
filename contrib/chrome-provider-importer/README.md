# CashPilot Provider Importer

Local Chrome helper for importing provider config and synchronizing one EarnApp account per Chrome profile with CashPilot.

## Install

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select `contrib/chrome-provider-importer`.

## Use

1. Open and sign in to CashPilot Settings at `https://cashpilot.4gmt.com` (or another HTTPS hostname under `4gmt.com`) in Chrome.
2. Open a logged-in provider tab.
3. Click the CashPilot Provider Importer extension.
4. Press **Scan current tab**.
5. Review the setting keys found.
6. Press **Save to CashPilot**.

Values are never printed in the popup. The extension only saves keys explicitly mapped in `extractor.js`. All provider imports use the same HTTPS `4gmt.com` CashPilot origin; plaintext HTTP/IP destinations are rejected.

## EarnApp account import

1. Use a separate Chrome profile for each EarnApp account.
2. Sign in at `https://earnapp.com` in that profile.
3. Keep the authenticated CashPilot Settings tab open.
4. Enter the account label/email and choose Google or Apple.
5. Press **Import and bind account** once.

The first import is always explicit. After it succeeds, that Chrome profile is permanently bound in extension-local storage to the same CashPilot server and EarnApp account. Changes to the exact allowlisted EarnApp cookies schedule a background refresh; accounts that were never imported are never synchronized. Automatic Google/Apple logout, password entry, MFA, OTP, and CAPTCHA handling are intentionally excluded.

The extension reads only these cookies from the `earnapp.com` domain:

- `auth`
- `auth-method`
- `oauth-refresh-token`
- `oauth-token`
- `xsrf-token`
- `brd_sess_id`
- `cg_uuid`

It does not read Google or Apple cookies, store token values in extension storage, show values in the popup, or write them to logs. CashPilot must be open and owner-authenticated for a background refresh to succeed.

## Supported import keys

- Traffmonetizer: `traffmonetizer_token`
- PacketStream: `packetstream_auth_token`, `packetstream_cid`
- Spide: `spide_dashboard_token`
- URnetwork: `urnetwork_api_key`, `urnetwork_email`, `urnetwork_password`
- ProxyBase dashboard: `proxybase_dashboard_access_token`
- IPRoyal Pawns: `iproyal_collector_email`, `iproyal_collector_password`, `iproyal_device_name`, `iproyal_device_id`
- Proxies.sx: `proxies-sx_api_key`
- Repocket: `repocket_email`, `repocket_api_key`
- Mysterium: `mysterium_dashboard_password`, `mysterium_mmn_api_key`

Providers that require an account password, OTP, captcha, or local desktop seed still need their normal Settings/file flow.
