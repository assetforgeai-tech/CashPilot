"""Read-only, account-scoped EarnApp dashboard collector."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import httpx

from app.collectors import base

API_BASE = "https://earnapp.com/dashboard/api"
API_PARAMS = {"appid": "earnapp"}
AUTH_FAILURE_CODES = {401, 403}


def build_proxy_url(proxy: Mapping[str, Any]) -> str:
    protocol = str(proxy.get("protocol") or "").strip().lower()
    if protocol not in {"http", "socks5"}:
        raise ValueError("EarnApp collector proxy must be HTTP or SOCKS5")
    host = str(proxy.get("host") or "").strip()
    port = int(proxy.get("port") or 0)
    if not host or not 1 <= port <= 65535:
        raise ValueError("EarnApp collector proxy host/port is invalid")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    username = str(proxy.get("username") or "")
    password = str(proxy.get("password") or "")
    auth = ""
    if username or password:
        auth = f"{quote(username, safe='')}:{quote(password, safe='')}@"
    return f"{protocol}://{auth}{host}:{port}"


def _float(value: Any) -> float:
    try:
        return float(str(value).replace("$", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _payload_devices(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, Mapping):
        return []
    for key in ("devices", "items", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _status_for(statuses: Any, device_id: str) -> Any:
    if isinstance(statuses, Mapping):
        direct = statuses.get(device_id)
        if direct is not None:
            return direct
        for key in ("statuses", "devices", "data"):
            nested = statuses.get(key)
            if isinstance(nested, Mapping) and device_id in nested:
                return nested[device_id]
            if isinstance(nested, list):
                for item in nested:
                    if (
                        isinstance(item, Mapping)
                        and str(item.get("device_id") or item.get("uuid") or item.get("id") or "") == device_id
                    ):
                        return item
    return None


def _online(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (list, tuple)):
        return bool(value and value[0])
    if isinstance(value, Mapping):
        if "online" in value:
            return bool(value.get("online"))
        value = value.get("status") or value.get("state") or value.get("connection_status")
    return str(value or "").strip().lower() in {"online", "connected", "active", "green", "enabled"}


def _device_id(raw: Mapping[str, Any]) -> str:
    return str(raw.get("device_id") or raw.get("uuid") or raw.get("id") or "").strip()


def _device_for(payload: Any, device_id: str) -> dict[str, Any] | None:
    for row in _payload_devices(payload):
        if _device_id(row) == device_id:
            return row
    return None


def _banned(device: Mapping[str, Any] | None) -> bool:
    if not isinstance(device, Mapping):
        return False
    return bool(device.get("banned") or device.get("is_banned"))


def normalize_snapshot(user_data: Any, money: Any, devices_payload: Any, statuses: Any) -> dict[str, Any]:
    user = dict(user_data) if isinstance(user_data, Mapping) else {}
    balances = dict(money) if isinstance(money, Mapping) else {}
    devices: list[dict[str, Any]] = []
    for raw in _payload_devices(devices_payload):
        device_id = str(raw.get("device_id") or raw.get("uuid") or raw.get("id") or "").strip()
        if not device_id:
            continue
        node = raw.get("node") if isinstance(raw.get("node"), Mapping) else {}
        share = raw.get("share") if isinstance(raw.get("share"), Mapping) else {}
        status = _status_for(statuses, device_id)
        devices.append(
            {
                "device_id": device_id,
                "ip": str(node.get("ip") or raw.get("ip") or raw.get("public_ip") or ""),
                "rate": _float(share.get("rate", raw.get("rate"))),
                "bandwidth": _float(raw.get("bandwidth", raw.get("traffic"))),
                "online": _online(status),
            }
        )
    balance = balances.get("money_balance", balances.get("balance", user.get("money_balance", user.get("balance"))))
    total = balances.get("money_total", balances.get("total", user.get("money_total", user.get("total"))))
    online = sum(1 for device in devices if device["online"])
    return {
        "status": "ok",
        "money_balance": _float(balance),
        "money_total": _float(total),
        "online_nodes": online,
        "offline_nodes": len(devices) - online,
        "devices": devices,
    }


class EarnAppAccountCollector:
    """One uncached collector bound to one account and one of its proxies."""

    def __init__(self, credentials: Mapping[str, Any], proxy: Mapping[str, Any]) -> None:
        raw_cookies = credentials.get("cookies") if isinstance(credentials, Mapping) else {}
        if not isinstance(raw_cookies, Mapping):
            raw_cookies = {}
        self.cookies = {str(key): str(value) for key, value in raw_cookies.items() if str(value)}
        self.proxy_url = build_proxy_url(proxy)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=30,
            cookies=self.cookies,
            proxy=self.proxy_url,
            follow_redirects=False,
        )

    @staticmethod
    def _headers(client: httpx.AsyncClient, fallback_cookies: Mapping[str, str]) -> dict[str, str]:
        xsrf = str(client.cookies.get("xsrf-token") or fallback_cookies.get("xsrf-token") or "")
        # Match the dashboard's browser contract for authenticated XHR calls.
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://earnapp.com",
            "Referer": "https://earnapp.com/dashboard/",
        }
        if xsrf:
            headers["xsrf-token"] = xsrf
        return headers

    async def link_and_verify_device(self, device_id: str, *, platform: str = "macos") -> dict[str, Any]:
        """Link one device through its account proxy and return secret-free dashboard evidence."""
        uuid = str(device_id or "").strip()
        if not uuid:
            return {"status": "error", "error_kind": "shape", "error": "EarnApp device id is required"}
        client = self._client()
        try:
            rotate = await client.get(f"{API_BASE}/sec/rotate_xsrf", params=API_PARAMS)
            if rotate.status_code in AUTH_FAILURE_CODES:
                return {"status": "error", "error_kind": "auth", "error": "authentication rejected"}
            rotate.raise_for_status()
            headers = self._headers(client, self.cookies)
            user_response = await client.get(f"{API_BASE}/user_data", params=API_PARAMS, headers=headers)
            if user_response.status_code in AUTH_FAILURE_CODES:
                return {"status": "error", "error_kind": "auth", "error": "authentication rejected"}
            user_response.raise_for_status()

            devices_response = await client.get(f"{API_BASE}/devices", params=API_PARAMS, headers=headers)
            if devices_response.status_code in AUTH_FAILURE_CODES:
                return {"status": "error", "error_kind": "auth", "error": "authentication rejected"}
            devices_response.raise_for_status()
            device = _device_for(devices_response.json(), uuid)
            link_attempted = device is None
            if link_attempted:
                xsrf = str(client.cookies.get("xsrf-token") or self.cookies.get("xsrf-token") or "")
                if not xsrf:
                    return {"status": "error", "error_kind": "auth", "error": "EarnApp XSRF unavailable"}
                link_response = await client.post(
                    f"{API_BASE}/link_device",
                    params=API_PARAMS,
                    headers=headers,
                    json={"uuid": uuid, "platform": platform},
                )
                if link_response.status_code in AUTH_FAILURE_CODES:
                    return {"status": "error", "error_kind": "auth", "error": "authentication rejected"}
                link_response.raise_for_status()
                devices_response = await client.get(f"{API_BASE}/devices", params=API_PARAMS, headers=headers)
                if devices_response.status_code in AUTH_FAILURE_CODES:
                    return {"status": "error", "error_kind": "auth", "error": "authentication rejected"}
                devices_response.raise_for_status()
                device = _device_for(devices_response.json(), uuid)

            if device is None:
                return {
                    "status": "pending",
                    "device_id": uuid,
                    "authenticated": True,
                    "link_attempted": link_attempted,
                    "device_present": False,
                    "online": False,
                    "banned": False,
                }
            status_response = await client.post(
                f"{API_BASE}/device_statuses",
                params=API_PARAMS,
                headers=headers,
                json={"data": {"devices": [uuid]}},
            )
            if status_response.status_code in AUTH_FAILURE_CODES:
                return {"status": "error", "error_kind": "auth", "error": "authentication rejected"}
            status_response.raise_for_status()
            online = _online(_status_for(status_response.json(), uuid))
            banned = _banned(device)
            return {
                "status": "online" if online and not banned else "offline",
                "device_id": uuid,
                "authenticated": True,
                "link_attempted": link_attempted,
                "device_present": True,
                "online": online,
                "banned": banned,
            }
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ProxyError):
            return {"status": "error", "error_kind": "route", "error": "proxy unavailable"}
        except httpx.HTTPStatusError as exc:
            kind = base.classify_exception(exc)
            return {
                "status": "error",
                "error_kind": "auth" if kind == base.KIND_AUTH else "route",
                "error": "authentication rejected" if kind == base.KIND_AUTH else "EarnApp route unavailable",
            }
        except (TypeError, ValueError, KeyError):
            return {"status": "error", "error_kind": "shape", "error": "EarnApp API shape changed"}
        finally:
            await client.aclose()

    async def collect_snapshot(self) -> dict[str, Any]:
        try:
            client = self._client()
            try:
                rotate = await client.get(f"{API_BASE}/sec/rotate_xsrf", params=API_PARAMS)
                if rotate.status_code in AUTH_FAILURE_CODES:
                    return {"status": "error", "error_kind": "auth", "error": "authentication rejected"}
                rotate.raise_for_status()
                headers = self._headers(client, self.cookies)

                user_response = await client.get(f"{API_BASE}/user_data", params=API_PARAMS, headers=headers)
                money_response = await client.get(f"{API_BASE}/money", params=API_PARAMS, headers=headers)
                devices_response = await client.get(f"{API_BASE}/devices", params=API_PARAMS, headers=headers)
                for response in (user_response, money_response, devices_response):
                    if response.status_code in AUTH_FAILURE_CODES:
                        return {"status": "error", "error_kind": "auth", "error": "authentication rejected"}
                    response.raise_for_status()
                devices = _payload_devices(devices_response.json())
                device_ids = [_device_id(item) for item in devices]
                device_ids = [device_id for device_id in device_ids if device_id]
                statuses: Any = {}
                if device_ids:
                    status_response = await client.post(
                        f"{API_BASE}/device_statuses",
                        params=API_PARAMS,
                        headers=headers,
                        json={"data": {"devices": device_ids}},
                    )
                    if status_response.status_code in AUTH_FAILURE_CODES:
                        return {"status": "error", "error_kind": "auth", "error": "authentication rejected"}
                    status_response.raise_for_status()
                    statuses = status_response.json()
                return normalize_snapshot(
                    user_response.json(),
                    money_response.json(),
                    devices_response.json(),
                    statuses,
                )
            finally:
                await client.aclose()
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ProxyError):
            return {"status": "error", "error_kind": "route", "error": "proxy unavailable"}
        except httpx.HTTPStatusError as exc:
            kind = base.classify_exception(exc)
            return {
                "status": "error",
                "error_kind": "auth" if kind == base.KIND_AUTH else "route",
                "error": "authentication rejected" if kind == base.KIND_AUTH else "EarnApp route unavailable",
            }
        except (TypeError, ValueError, KeyError):
            return {"status": "error", "error_kind": "shape", "error": "EarnApp API shape changed"}
