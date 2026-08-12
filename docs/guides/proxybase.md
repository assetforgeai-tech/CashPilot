# ProxyBase

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://proxybase.org](https://proxybase.org)

## Description

ProxyBase is a bandwidth-sharing platform that pays users in cryptocurrency for sharing their unused internet connection. CashPilot now keeps two tokens separate: one to start the peer node, and one to read the dashboard later. Residential IPs earn the most, but datacenter IPs are also supported — they currently receive less traffic than residential. Official multi-arch Docker image (amd64/arm64/armv7).

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $5 (estimate) |
| Per | device |
| Minimum payout | $1 |
| Payout frequency | On request |
| Payment methods | Crypto |

> Crypto payouts. Earnings depend on location and bandwidth usage.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| VPS/Datacenter IP | Yes -- supported, but currently receives less traffic than residential |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker (amd64/arm64/armv7), Windows, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [ProxyBase](https://peer.proxybase.org?referral=nXzS3c6iTO). If the referral field is not pre-filled, enter referral code `nXzS3c6iTO` in the **Referral Code** box before creating your account.

### 2. Get your Access Tokens

After signing up and verifying your email, open your [dashboard](https://peer.proxybase.org/dashboard).

- Copy the **Deploy Access Token** from the Docker command on the setup page. CashPilot uses this to start the node.
- Copy the **Dashboard Access Token** for dashboard reads and sync later. CashPilot stores it separately.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **ProxyBase** in the service catalog and click **Deploy**. Enter the deploy token and a device name. Put the dashboard token in the dashboard/session field.

> **Upgrading from an older CashPilot?** ProxyBase moved to a new client image and replaced its credentials: the old `USER_ID`/`DEVICE_NAME` values are retired and cannot be reused. Generate fresh deploy/dashboard tokens in your [dashboard](https://peer.proxybase.org/dashboard), then re-deploy ProxyBase from the catalog with them (plus a Device Name) — existing containers built on the old image have stopped earning.

## Docker Configuration

- **Image:** `ghcr.io/proxybaseorg/peer-cli@sha256:b78dda3969019eb9e0d3ba0aeba0929148337898b00d99cf780f4d8c99b31b0e` (digest-pinned; the catalog entry is authoritative if they ever differ)
- **Platforms:** linux/amd64, linux/arm64, linux/arm/v7

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `NAME` | Device Name | Yes | No | Any name to identify this device in your ProxyBase dashboard (default: `cashpilot-{hostname}`) |

### Deploy Credentials

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `deploy_access_token` | Deploy Access Token | Yes | Yes | Token shown on the setup page; used to launch the peer node |

### Dashboard Credentials

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `dashboard_access_token` | Dashboard Access Token | Yes | Yes | Token used to read dashboard data later |

## Troubleshooting

### ProxyBase shows "running" but earnings stopped (or dropped to $0)

If ProxyBase was deployed before the migration to the new client, the container is still running ProxyBase's **retired** image — it looks healthy in the dashboard but no longer earns, because the old backend was shut down. The dashboard cannot tell the retired client from the current one.

Fix: **Remove** the ProxyBase service, then **Deploy** it again from the catalog and paste fresh deploy/dashboard tokens from [your dashboard](https://peer.proxybase.org/dashboard). The redeploy pulls the current `ghcr.io/proxybaseorg/peer-cli` image.

### Container exits immediately after deploy

The client exits with `Missing ID and NAME` when it starts without credentials. CashPilot's deploy form requires both fields, so this normally can't happen — but if you deployed with an exported compose file, make sure the `NAME` environment variable is filled in and the deploy token is present in the server-side deploy credential field.
