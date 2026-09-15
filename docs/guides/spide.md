# Spide

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://spide.network](https://spide.network)

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

After signing up, CashPilot uses the account email/password only for server-side device-key registration. The dashboard token/cookie is a separate credential used only for the registration API.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Spide** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `alpine:3.20`

### Runtime boundary

The container runs only the Spide Linux CLI. It does not run the collector or dashboard code. CashPilot parses the CLI `Device key` from worker logs, then registers that key server-side through `POST /api/v1/device/create`.

> **Important:** `provider-runtime/provider_code_setup_node/spide.py` and the files
> under `provider-runtime/audit_code/spide/` are legacy reference/audit material.
> They must not be copied into the container: account login and dashboard
> collection belong to CashPilot server-side automation.
