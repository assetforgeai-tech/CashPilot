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

### 2. Get deploy auth token

Get `UR_AUTH_TOKEN` from the logged-in dashboard at [app.ur.network](https://app.ur.network). This token is used by the `bringyour/community-provider` container.

Optional: Account Settings also has API Key Management. Save an API key only when you want CashPilot to research/build a collector; it is not required for deploy.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **URnetwork** in the service catalog and click **Deploy**. Enter `UR_AUTH_TOKEN`; CashPilot forwards it to the worker container as `UR_AUTH_TOKEN`.

## Docker Configuration

- **Image:** `bringyour/community-provider`
- **Platforms:** linux/amd64, linux/arm64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `UR_AUTH_TOKEN` | Deploy auth token | Yes | Yes | Stored CashPilot deploy credential forwarded to the container as `UR_AUTH_TOKEN` |

## Collector Status

Logged-in client manager exposes Clients, Statistics, Providers, Wallet Stats, Account Settings, Balance Codes, Data Stats, Payout Stats, Generate Auth Client, and API Key Management. No collector/API response shape is confirmed yet.
