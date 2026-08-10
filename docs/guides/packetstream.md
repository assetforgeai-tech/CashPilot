# PacketStream

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://packetstream.io](https://packetstream.io)

## Description

PacketStream is a peer-to-peer bandwidth marketplace where you can sell your unused bandwidth. It powers a residential proxy network used for market research, SEO monitoring, and ad verification. The current setup is a desktop client with a CID (Client ID) from the dashboard; automated earnings collection is still awkward because login is CAPTCHA-protected.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $4 (estimate) |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Paypal |

> Pays $0.10/GB for bandwidth shared. Earnings depend heavily on demand for your IP's location.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Windows, Macos, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [PacketStream](https://packetstream.io/?psr=7xgZ).

### 2. Get your credentials

After signing up, open the dashboard and copy the CID shown in the setup page.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **PacketStream** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `packetstream/psclient`
- **Platforms:** linux/amd64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `CID` | Client ID | Yes | No | Your PacketStream Client ID (found in Dashboard > Setup) |
