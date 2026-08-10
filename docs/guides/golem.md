# Golem Network

> **Category:** GPU Compute | **Status:** Active
> **Website:** [https://golem.network](https://golem.network)

## Description

Golem Network is a decentralized compute marketplace where you share CPU and GPU resources in exchange for GLM tokens. Providers run the Yagna agent which manages workload execution in sandboxed environments. Current provider docs favor a host Docker-based provider install, but CashPilot does not package it as a single managed service container. Payments are in GLM.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $50 (estimate) |
| Per | device |
| Minimum payout |  |
| Payout frequency | Per task completion |
| Payment methods | Crypto |

> Earnings depend on hardware, pricing, and task demand. Current provider setup is a host-level Golem/Yagna provider install, commonly Docker-based, not a single CashPilot-managed image.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | No |
| Minimum bandwidth | 10 Mbps |
| GPU required | No |
| Minimum storage | 20GB |
| Supported platforms | Linux |

## Setup Instructions

### 1. Create an account

Sign up at [Golem Network](https://golem.network).

### 2. Get your credentials

Follow the current Golem provider documentation on the host. CashPilot can track the provider through local Yagna state once installed, but does not deploy the provider container itself.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Golem Network** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** ``
- **Platforms:** linux/amd64

### Environment Variables

No environment variables required.
