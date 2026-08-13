# CashPilot Live Test Redacted Summary

> Redacted operator summary. Do not paste raw cookies, wallet phrases, passwords, API keys, or session tokens here.

**Raw local evidence:** `D:\1. WORK_true\CashPilot\secret\provider-live-test-raw-2026-08.md`

**Primary success rule:** provider dashboard shows node online.

**Fallback success rule:** when a provider has no dashboard or no node-online indicator, Codex provides node-side evidence and the operator confirms manual-only.

## Test Surfaces

| Surface | Role | Destructive Scope | Status | Evidence |
| --- | --- | --- | --- | --- |
| `vps-test-sing` | Primary live-test worker | Clean/recreate allowed | blocked | worker `52-237-120-118-1786648057`, repo commit `8ba379a`, heartbeat HTTP 200; server cannot reach public `:8081` |
| `vps-test-us` | Secondary live-test worker | Conditional only | pending | not touched unless needed |
| Chrome profile 40 | Credential/session source | Read only; overwrite Settings only when stale | pending | tab inventory not captured |
| VPS server | Source of truth | No DB/volume edits | ready | deployed commit `bfe5835`, source-built UI/worker containers up, `active_services=19` matches deployed rows |

## Current Blocker

`vps-test-sing` publishes worker `0.0.0.0:8081`, and local checks on that VPS return `200` from `http://127.0.0.1:8081/api/health`. The VPS server times out when calling `http://52.237.120.118:8081`, so server-first deploys return `503 Worker communication failed`.

Required infra fix before continuing live rollout: allow inbound TCP `8081` to `vps-test-sing` from the VPS server public IP `42.96.13.215` in the cloud/network security group. Host `ufw` is inactive; the block is outside the container/app path.

## First Rollout Attempt

| Provider | Result | Cause |
| --- | --- | --- |
| adnade | blocked | worker communication failed |
| bitping | blocked | worker communication failed |
| grass | blocked | worker communication failed |
| mysterium | blocked | worker communication failed |
| proxybase | blocked | worker communication failed |
| proxybase-xyz | blocked | worker communication failed |
| proxylite | blocked | worker communication failed |
| spide | blocked | worker communication failed |
| uprock | blocked | worker communication failed |
| urnetwork | blocked | worker communication failed |
| wipter | blocked | worker communication failed |
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
