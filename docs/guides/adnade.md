# Adnade

> **Category:** DePIN | **Status:** Active
> **Website:** [https://adnade.net](https://adnade.net)

## Description

Adnade is a browser-based earning flow. CashPilot deploys it with the Chromium
container from the InternetIncome test branch and a pre-authenticated Chrome
profile bundle.

## Setup Instructions

### 1. Prepare the Chrome profile bundle

Use the encrypted `chromeprofiledata.ORIGINAL.zip.fernet` artifact stored in
R2. The worker downloads it directly, decrypts it with the saved Fernet key,
then unpacks the Chrome profile.

### 2. Save deploy credentials

In **Settings -> Provider Credentials -> Deploy runtime**, save:

- `Adnade username`
- `Chrome profile decrypt key`

### 3. Save collector credentials

In **Settings -> Provider Credentials -> Earnings collector**, save:

- `Adnade username`
- `Adnade password`

CashPilot logs in with the official `UserID` / `Passwort` form and reads
`Withdrawable balance` from the EUR/BTC payout page.

### 4. Deploy with CashPilot

CashPilot starts `lscr.io/linuxserver/chromium:latest`, downloads the encrypted
profile on the worker, unpacks it to `/config`, and opens:

```text
https://adnade.net/view.php?user=<ADNADE_USERNAME>&multi=4
```

## Docker Configuration

- **Image:** `lscr.io/linuxserver/chromium:latest`
- **Web UI port:** `3000` in the container, mapped from host port `4000`
- **Profile mount:** `/config`

## Notes

This import is intentionally Chrome-only. Firefox and generic custom-browser
InternetIncome flows were not brought into CashPilot.
