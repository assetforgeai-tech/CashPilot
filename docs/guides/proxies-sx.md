# Proxies.sx

> **Category:** Bandwidth Sharing | **Status:** Beta
> **Website:** [https://www.proxies.sx](https://www.proxies.sx)

## Description

Proxies.sx runs a peer device that sells bandwidth through the provider's relay.
The official SDK connects over WebSocket, registers the device with your API key,
then keeps it online with heartbeats. A device must move through CONNECTED,
VERIFIED, LISTED, and EARNING before it earns.

Online does not mean earning. The provider says earning requires a customer-routable
mobile or residential IP, correct geo/ASN quality, and at least 500 KB/s upload.
VPS and datacenter IPs may connect, but are generally not routed.

## Earning Estimates

| Metric | Value |
|--------|-------|
| Monthly range | Not documented |
| Per | device |
| Minimum payout | Unknown |
| Payout frequency | On request |
| Payment methods | Crypto |

## Requirements

| Requirement | Value |
|-------------|-------|
| Residential IP | Yes |
| Minimum bandwidth | 500 KB/s upload |
| GPU required | No |
| Minimum storage | None |
| Supported platforms | Docker, Linux, Windows, MacOS |

## Setup Instructions

### 1. Create an account

Sign up at [Proxies.sx](https://www.proxies.sx).

### 2. Get your API key

Open the Proxies.sx dashboard and create or copy your peer API key. The SDK
expects it as `API_KEY`.

### 3. Deploy with CashPilot

In the CashPilot web UI, find **Proxies.sx** in the bandwidth catalog and click
**Deploy**. Paste `API_KEY`. Optionally set `AGENT_NAME`; the default is
`cashpilot-{hostname}`.

CashPilot runs the provider's Node SDK in `node:20-alpine`, installs `ws`, and
downloads `https://agents.proxies.sx/peer/reference-sdk.js` into the persistent
`proxies-sx-data` volume on first start.

## Docker Configuration

- **Image:** `node:20-alpine`
- **Platforms:** linux/amd64, linux/arm64
- **Egress:** direct. Do not route this service through Proxy Egress; Proxies.sx
  grades the worker's real IP.

### Environment Variables

| Variable | Label | Required | Secret | Description |
|----------|-------|:--------:|:------:|-------------|
| `API_KEY` | API key | Yes | Yes | Peer API key from the Proxies.sx dashboard |
| `AGENT_NAME` | Agent name | No | No | Device name shown in the Proxies.sx peer dashboard |

## Troubleshooting

- `CONNECTED` plus `ACK` means the SDK is online.
- Earning starts later, after the device is verified, listed, and routed.
- If a VPS shows online but never earns, that matches the provider docs: datacenter
  IPs are generally not customer-routable.
- Registration is rate-limited. For fleets, stagger starts instead of booting every
  node at once.
