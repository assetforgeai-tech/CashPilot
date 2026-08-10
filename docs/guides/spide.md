# Spide

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://spide.io](https://spide.io)

## Description

Spide is a bandwidth-sharing service that lets you monetize unused internet bandwidth. The current CashPilot runtime downloads the official Linux CLI zip, starts it in Docker, then registers the emitted Device key through the dashboard API.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $3 (estimate) |
| Per | device |
| Minimum payout | $5 |
| Payout frequency | On request |
| Payment methods | Crypto |

> Limited information available. Earnings depend on location.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Windows, Linux |

## Setup Instructions

### 1. Create an account

Sign up at [Spide](https://spide.network/register.html?f3bc51).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Spide** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `alpine:3.20`

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `SPIDE_MACHINE_ID` | Machine ID | No | No | Machine ID for existing device already registered (auto-generated if empty) |
