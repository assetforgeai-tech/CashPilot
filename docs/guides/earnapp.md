# EarnApp

> **Category:** Bandwidth Sharing | **Status:** Active
> **Website:** [https://earnapp.com](https://earnapp.com)

!!! danger "EarnApp prohibits the way CashPilot runs it — read this first"

    EarnApp's help centre states: **"Installing EarnApp on Virtual Machines
    (VMs), Docker containers, or hosting services is strictly prohibited."** It
    names **personal or home servers** and **"any device used for business or
    monetization purposes"** as prohibited environments, and says the penalty is
    that your **account is terminated without prior notice** and any **pending
    payments are cancelled**.

    CashPilot deploys every service as a Docker container, usually on a home
    server. **Deploying EarnApp through CashPilot means knowingly accepting that
    risk.** This guide is kept so the decision is an informed one, not so the
    risk is hidden behind a signup link.

    EarnApp does support ordinary desktops, laptops, phones and Raspberry Pi via
    its own installer. If you want to earn with it, that is the route that does
    not put your account and balance at risk — and CashPilot cannot manage it.

## Description

EarnApp by Bright Data lets residential devices earn from contributed network usage. Its official model is now fixed-rate pay-per-time, not pay-per-GB. Official support prohibits VM, Docker, hosting, personal/home server, and business/monetization environments, so the community Docker image is a known account-risk path rather than the provider's intended setup.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $10 (estimate) |
| Per | device |
| Minimum payout | $10 |
| Payout frequency | On request (auto-redeem available: PayPal $10 min, Wise $10 min, Amazon $50 min) |
| Payment methods | Paypal, Amazon Giftcard, Wise |

> Official rates are pay-per-time: up to $10/IP/month in the US and up to $5/IP/month elsewhere, depending on active use and demand.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | 10 Mbps recommended; 100 Mbps recommended for US max rate |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Windows, Macos, Linux, Android, iOS |

## Setup Instructions

### 1. Create an account

Sign up at [EarnApp](https://earnapp.com/i/TSMD9wSm).

### 2. Get your credentials

After signing up, locate the credentials needed for Docker deployment. These are typically your email/password or an API token found in the dashboard.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **EarnApp** in the service catalog and click **Deploy**. Enter the required credentials and CashPilot will handle the rest.

## Docker Configuration

- **Image:** `fazalfarhan01/earnapp:lite`
- **Platforms:** linux/amd64

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `EARNAPP_UUID` | Node UUID | Yes | No | Your EarnApp node ID (run 'earnapp showid' to get it, or generate one with the sdk-node-id format) |
| `EARNAPP_TERM` | Accept Terms | No | No | Set to 'yes' to accept terms of service (default: `yes`) |
