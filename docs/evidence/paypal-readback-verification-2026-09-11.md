# PayPal read-back verification - 2026-09-11

## Live result

- `cashpilot-ui` runs `ghcr.io/assetforgeai-tech/cashpilot:1.32.6`, healthy.
- A controlled PayPal-pool configuration attempt for account `2` returned HTTP `409` with `payment configuration could not be verified`.
- EarnApp returned a successful payment POST in earlier attempts but then returned `404` from `redeem_details`; the old code incorrectly surfaced `configured=false` with HTTP `200`.
- The fixed code requires read-back confirmation of both `configured=true` and the requested payment method.
- The PayPal destination remains fixed/assigned to account `2`; it is not released or reassigned after an unverifiable remote result.
- Account snapshots remain `configured=false`; no false auto-redeem success is recorded.

## Safety

- No raw PayPal destination, token, cookie, or upstream response body is stored in this evidence.
- The worker was not restarted or recreated during the UI deployment.
- SQLite integrity remains `ok`, with zero foreign-key errors.

## Remaining action

EarnApp's external payment endpoint must successfully return a verified `redeem_details` record before auto-redeem can be marked active. The UI/API now reports the pending verification state instead of claiming success.
