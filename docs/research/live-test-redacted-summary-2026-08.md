# CashPilot Live Test Redacted Summary

> Redacted operator summary. Do not paste raw cookies, wallet phrases, passwords, API keys, or session tokens here.

**Raw local evidence:** `D:\1. WORK_true\CashPilot\secret\provider-live-test-raw-2026-08.md`

**Primary success rule:** provider dashboard shows node online.

**Fallback success rule:** when a provider has no dashboard or no node-online indicator, Codex provides node-side evidence and the operator confirms manual-only.

## Test Surfaces

| Surface | Role | Destructive Scope | Status | Evidence |
| --- | --- | --- | --- | --- |
| `vps-test-sing` | Primary live-test worker | Clean/recreate allowed | active | worker `52-237-120-118-1786648057`, repo commit `8ba379a`, heartbeat HTTP 200; server now reaches public `:8081` |
| `vps-test-us` | Secondary live-test worker | Conditional only | pending | not touched unless needed |
| Chrome profile 40 | Credential/session source | Read only; overwrite Settings only when stale | pending | tab inventory not captured |
| VPS server | Source of truth | No DB/volume edits | ready | deployed commit `bfe5835`, source-built UI/worker containers up, `active_services=19` matches deployed rows |

## Current Blocker

Resolved: `vps-test-sing` now answers the VPS server on `http://52.237.120.118:8081/api/health`.

First post-firewall rollout used worker `52-237-120-118-1786648057` and proxy lease `vtproxy` endpoint `dc-t5.proxyvt.com:41231`.

## First Rollout Attempt

| Provider | Result | Cause |
| --- | --- | --- |
| adnade | failed | worker deploy failed after R2 profile download; no container created |
| bitping | running | container `cashpilot-bitping` running after 5-minute check |
| grass | running | container `cashpilot-grass` running after 5-minute check |
| mysterium | partial | container running, but logs show TUN/sudo permission failure during WireGuard session |
| proxybase | running | container `cashpilot-proxybase` running after 5-minute check |
| proxybase-xyz | running | container now uses `HOME=/home/proxybase`; seller daemon running in foreground |
| proxylite | running | container `cashpilot-proxylite` running after 5-minute check |
| spide | failed | container restarts; CLI zip checksum mismatch |
| uprock | failed | worker deploy failed; no container created |
| urnetwork | running | container `cashpilot-urnetwork` running after 5-minute check |
| wipter | running | container `cashpilot-wipter` running after 5-minute check |
| earnapp | blocked | missing deploy field: Node UUID |
| earnfm | blocked | missing deploy field: API Key |
| iproyal | blocked | missing deploy fields: Email, Password |
| packetstream | blocked | missing deploy field: Client ID |
| proxies-sx | blocked | missing deploy field: API key |
| proxyrack | blocked | missing deploy field: Device UUID |
| repocket | blocked | missing deploy fields: Email, API Key |
| traffmonetizer | blocked | missing deploy field: Token |

## Provider Success Matrix

| Provider | Dashboard Online Check | Node-Side Evidence To Provide If Manual | Final Signal | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| adnade | provider/dashboard node online if exposed | noVNC URL, container name, browser URL, logs | pending | pending | Dawn/Titan ride this profile runtime. |
| dawn | dashboard/session node online if exposed | Adnade profile extension state, logs, provider page | pending | pending | Collector/session only; no separate deploy if bundled with Adnade. |
| titan | dashboard/session node online if exposed | Adnade profile extension state, logs, provider page | pending | pending | Collector/session only; no separate deploy if bundled with Adnade. |
| grass | dashboard node online | container logs, worker provider state | pending | pending | Direct-IP provider. |
| uprock | dashboard node online | container logs, worker provider state | pending | pending | Direct-IP provider. |
| wipter | dashboard node online if exposed | container logs, login-ready marker, worker provider state | pending | pending | Provider tunnel namespace. |
| bitping | dashboard node online | container logs, worker provider state | pending | pending | Direct-IP provider. |
| earnapp | dashboard node online | container logs, worker provider state | pending | pending | Policy depends on catalog egress mode. |
| earnfm | dashboard node online | container logs, worker provider state | pending | pending | Direct-IP provider. |
| iproyal | dashboard node online | container logs, worker provider state | pending | pending | Pawns/IPRoyal. |
| mysterium | MYST dashboard/provider state registered/online | container logs, 127.0.0.1:4449 tunnel, wallet lease state | pending | pending | MYST wallet-backed provider. |
| packetstream | dashboard node online | container logs, worker provider state | pending | pending | Policy depends on catalog egress mode. |
| proxies-sx | dashboard node online | container logs, worker provider state | pending | pending | Connected is not necessarily earning. |
| proxybase | dashboard node online or provider node count | container logs, worker provider state | pending | pending | Docker `peer-cli` provider. |
| proxybase-xyz | no dashboard node-online assumed | CLI state, container logs, worker provider state | pending | pending | Manual-only if no dashboard evidence exists. |
| proxylite | provider node count if exposed | container logs, worker provider state | pending | pending | Manual-only if no dashboard evidence exists. |
| proxyrack | dashboard node online | container logs, worker provider state | pending | pending | Direct-IP provider. |
| repocket | dashboard node online | container logs, worker provider state | pending | pending | Direct-IP provider. |
| spide | dashboard node online if exposed | CLI device status, container logs, worker provider state | pending | pending | Device flow. |
| traffmonetizer | dashboard node online | container logs, worker provider state | pending | pending | Direct-IP provider. |
| urnetwork | dashboard node online | container logs, worker provider state | pending | pending | Chrome/session audit source. |

## Operator Confirmation Pack

For every manual-only provider, provide:

- Worker name and public IP.
- Provider slug and container/service name.
- Open URL or tunnel URL if the provider has a local UI.
- Exact non-secret CLI command to inspect process/log state.
- Last 30 log lines with secrets redacted.
- CashPilot worker `provider_states` row if available.
