# Grass

> **Category:** DePIN | **Status:** Active
> **Website:** [https://www.grass.io](https://www.grass.io)

## Description

Grass is a decentralized network that lets you sell your unused bandwidth for AI training data. It operates as a browser extension and desktop app, routing web scraping requests through your connection to build structured datasets. With 8.5M+ users, it is one of the largest DePIN bandwidth networks. Earns GRASS tokens on the Solana blockchain.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | $0 - $10 (estimate) |
| Per | device |
| Minimum payout |  |
| Payout frequency | Epoch-based airdrop |
| Payment methods | Crypto |

> Earns Grass Points convertible to GRASS tokens via airdrops. Actual USD value depends on token price. Browser extension or desktop app required.

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | None |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Browser-Extension, Windows, Macos, Android, Ios |

## Setup Instructions

### 1. Create an account

Sign up at [Grass](https://app.grass.io/register?referralCode=kn8FNEPnUr2tMqE).

### 2. Get collector credential

For earnings collection, copy a fresh `accessToken` from the logged-in Grass dashboard or desktop profile.

### 3. Runtime

CashPilot resolves Grass' official desktop installer manifest when a new node is installed, picks the matching Linux build, builds a local noVNC Docker wrapper, and then runs it with the saved seed/profile bundle. Restart uses the resolved image; latest is not re-resolved on every container restart.

## Docker Configuration

- **Image:** `cashpilot/grass-desktop:auto`
- **Installer manifest:** `https://files.grass.io/file/grass-extension-upgrades/desktop-installer-latest.json`
- **Platforms:** browser-extension, windows, macos, linux, android, ios

### Environment Variables

No environment variables required.

## Collector Credentials

| Key | Description |
|-----|-------------|
| `access_token` | Grass dashboard/profile `accessToken`; collector-only, not a Docker runtime env |
