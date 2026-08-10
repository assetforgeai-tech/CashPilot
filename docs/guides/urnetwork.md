# URnetwork

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://ur.io](https://ur.io)

## Description

URnetwork is a decentralized VPN and bandwidth-sharing network. You earn by providing bandwidth as a community provider. Uses JWT-based authentication. Official Docker image from Bring Your Own (bringyour). Supports both direct mode (with tun device) and proxy mode (SOCKS5).

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $5 (estimate) |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Crypto |

> Works on VPS and residential. Crypto payouts. Supports proxy mode for multi-IP setups.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Windows, Macos, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [URnetwork](https://ur.io/?referral_code=1Q3G19).

### 2. Get auth token

Get `UR_AUTH_TOKEN` from the logged-in dashboard local storage. It is a JWT used by the community provider container.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **URnetwork** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `bringyour/community-provider`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `UR_AUTH_TOKEN` | Auth Token | Yes | Yes | Your URnetwork authentication token from the dashboard |

## Collector Status

Logged-in client manager exposes Clients, Statistics, Providers, Wallet Stats, Account Settings, Balance Codes, Data Stats, and Payout Stats. In the audited browser session, wallet/stat endpoints returned 401 and there were 0 clients, so no collector/API contract is confirmed yet.
