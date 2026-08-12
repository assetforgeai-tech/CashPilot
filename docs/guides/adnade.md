# Adnade

> **Category:** DePIN | **Status:** Active
> **Website:** [https://adnade.net](https://adnade.net)

## Description

Adnade is a browser-based earning flow. CashPilot deploys it with the Chromium
container from the InternetIncome test branch and a pre-authenticated Chrome
profile bundle.

## Setup Instructions

### 1. Prepare the Chrome profile bundle

Use `chromeprofiledata.ORIGINAL.zip` that already contains the connected Dawn
and Titan extensions.

### 2. Save deploy credentials

In **Settings -> Provider Credentials -> Deploy runtime**, save:

- `Adnade username`
- `Chrome profile bundle`

### 3. Deploy with CashPilot

CashPilot starts `lscr.io/linuxserver/chromium:latest`, mounts the unpacked
profile to `/config`, and opens:

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
