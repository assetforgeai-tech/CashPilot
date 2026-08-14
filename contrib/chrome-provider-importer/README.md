# CashPilot Provider Importer

Local Chrome helper for importing provider config from a logged-in provider tab into CashPilot Settings.

## Install

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select `contrib/chrome-provider-importer`.

## Use

1. Open and sign in to CashPilot Settings in Chrome.
2. Open a logged-in provider tab.
3. Click the CashPilot Provider Importer extension.
4. Press **Scan current tab**.
5. Review the setting keys found.
6. Press **Save to CashPilot**.

Values are never printed in the popup. The extension only saves keys explicitly mapped in `extractor.js`.

## Supported import keys

- Traffmonetizer: `traffmonetizer_token`
- PacketStream: `packetstream_auth_token`, `packetstream_cid`
- Grass: `grass_access_token`, `grass_store_access_token`, `grass_store_refresh_token`, `grass_store_token_expiry`, `grass_store_wynd_user_id`
- Spide: `spide_dashboard_token`
- URnetwork: `urnetwork_auth_token`, `urnetwork_api_key`
- ProxyBase dashboard: `proxybase_dashboard_access_token`
- ProxyLite: `proxylite_user_id`
- IPRoyal Pawns: `iproyal_email`, `iproyal_password`, `iproyal_device_name`, `iproyal_device_id`
- Proxies.sx: `proxies-sx_api_key`
- Repocket: `repocket_email`, `repocket_api_key`
- Mysterium: `mysterium_dashboard_password`, `mysterium_mmn_api_key`

Providers that require an account password, OTP, captcha, or local desktop seed still need their normal Settings/file flow.
